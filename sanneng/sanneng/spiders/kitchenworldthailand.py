import scrapy
import re
from urllib.parse import parse_qs, urlparse, urlencode, urlunparse


class KitchenworldthailandSpider(scrapy.Spider):
    name = "kitchenworldthailand"
    allowed_domains = ["kitchenworldthailand.com"]
    start_urls = ["https://kitchenworldthailand.com/en/product?type=5&cat=71&page=1"]

    custom_settings = {
        "ROBOTSTXT_OBEY": False,
    }

    def parse(self, response):
        cards = response.css("div.product-list ul.item-list > li.item")

        listing_category = response.css("div.product-cover h4.title::text").get(default="").strip()

        if not cards:
            self.logger.warning("No product cards found on %s", response.url)
            return

        for card in cards:
            product_href = (
                card.css("div.content a.link.txt::attr(href)").get()
                or card.css("div.thumb a.link[href*='/en/product/detail/']::attr(href)").get()
            )
            if not product_href:
                continue

            listing_name = " ".join(
                [
                    text.strip()
                    for text in card.css("div.content a.link.txt::text").getall()
                    if text and text.strip()
                ]
            )
            listing_desc = " ".join(
                [
                    text.strip()
                    for text in card.css("div.content div.desc *::text").getall()
                    if text and text.strip()
                ]
            )
            listing_image = card.css("div.thumb figure.contain img::attr(src)").get(default="").strip()

            raw_price = " ".join(
                [
                    text.strip()
                    for text in card.css("div.content div.price *::text").getall()
                    if text and text.strip() and text.strip() != "&nbsp;"
                ]
            )
            listing_price = self._extract_price(raw_price)

            listing_product_id = card.css("a.btn-favorite::attr(data-id)").get(default="").strip()

            yield response.follow(
                product_href,
                callback=self.parse_product,
                meta={
                    "listing_name": listing_name,
                    "listing_desc": listing_desc,
                    "listing_image": response.urljoin(listing_image) if listing_image else "",
                    "listing_price": listing_price,
                    "listing_product_id": listing_product_id,
                    "listing_category": listing_category,
                },
            )

        next_page_url = self._build_next_page_url(response.url)
        current_page = self._current_page(response.url)
        max_pages = int(getattr(self, "max_pages", 200) or 200)
        if next_page_url and current_page < max_pages:
            yield scrapy.Request(next_page_url, callback=self.parse)

    def parse_product(self, response):
        page_title = response.css("title::text").get(default="").strip()
        name = " ".join(
            [
                text.strip()
                for text in response.css("div.product-data div.title *::text").getall()
                if text and text.strip()
            ]
        )
        if not name:
            name = response.meta.get("listing_name", "")

        description_parts = [
            text.strip()
            for text in response.css("article.editor-content *::text").getall()
            if text and text.strip()
        ]
        description = "\n".join(description_parts)
        if not description:
            description = response.css("meta[name='description']::attr(content)").get(default="").strip()
        if not description:
            description = response.meta.get("listing_desc", "")

        detail_image_urls = []
        for href in response.css(
            "div.slider-for a[data-fancybox='product-slider']::attr(href), "
            "div.slider-for figure.contain img::attr(src), "
            "div.slider-nav figure.contain img::attr(src), "
            "meta[property='og:image']::attr(content)"
        ).getall():
            if not href:
                continue
            absolute = response.urljoin(href)
            if absolute and absolute not in detail_image_urls:
                detail_image_urls.append(absolute)

        image_url = detail_image_urls[0] if detail_image_urls else response.meta.get("listing_image", "")

        detail_price_text = " ".join(
            [
                text.strip()
                for text in response.css("div.product-data div.price *::text").getall()
                if text and text.strip() and text.strip() != "&nbsp;"
            ]
        )
        price = self._extract_price(detail_price_text) or response.meta.get("listing_price", "")

        product_id = response.css("a.btn-favorite::attr(data-id)").get(default="").strip()
        if not product_id:
            product_id = response.meta.get("listing_product_id", "") or self._extract_product_id(response.url)

        sku_candidates = [name, page_title, description, response.url]
        sku = ""
        for candidate in sku_candidates:
            sku = self._extract_sku(candidate)
            if sku:
                break

        yield {
            "name": name,
            "title": page_title,
            "sku": sku,
            "price": price,
            "original_price": "",
            "product_id": product_id,
            "product_url": response.url,
            "image_url": image_url,
            "detail_image_urls": detail_image_urls,
            "detail_image_count": len(detail_image_urls),
            "description": description,
            "brand": "SANNENG",
            "category": response.meta.get("listing_category", ""),
        }

    @staticmethod
    def _extract_price(text):
        if not text:
            return ""
        match = re.search(r"(\d[\d,]*\.?\d*)", str(text).replace("\u00a0", " "))
        if not match:
            return ""
        return match.group(1).replace(",", "")

    @staticmethod
    def _extract_sku(text):
        if not text:
            return ""

        value = str(text)

        prioritized = re.search(r"\b(?:SN|TIP|TS|DB|DE)[\s\-]*\d+[A-Z0-9.-]*\b", value, re.IGNORECASE)
        if prioritized:
            return re.sub(r"[^A-Z0-9]", "", prioritized.group(0).upper())

        generic = re.search(r"\b[A-Z]{1,6}[\s\-]*\d{2,8}[A-Z0-9.-]*\b", value, re.IGNORECASE)
        if generic:
            return re.sub(r"[^A-Z0-9]", "", generic.group(0).upper())

        return ""

    @staticmethod
    def _extract_product_id(url):
        match = re.search(r"/detail/(\d+)", url)
        return match.group(1) if match else ""

    @staticmethod
    def _current_page(url):
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        try:
            return int((query.get("page") or ["1"])[0])
        except (TypeError, ValueError):
            return 1

    @staticmethod
    def _build_next_page_url(url):
        parsed = urlparse(url)
        query = parse_qs(parsed.query)

        current_page = 1
        if "page" in query:
            try:
                current_page = int(query["page"][0])
            except (TypeError, ValueError):
                current_page = 1

        query["page"] = [str(current_page + 1)]
        next_query = urlencode(query, doseq=True)
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, next_query, parsed.fragment))
