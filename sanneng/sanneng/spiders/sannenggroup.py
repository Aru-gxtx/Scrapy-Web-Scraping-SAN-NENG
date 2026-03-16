import scrapy
import re
from urllib.parse import urlparse, parse_qs


class SannenggroupSpider(scrapy.Spider):
    name = "sannenggroup"
    allowed_domains = ["sannenggroup.com"]
    start_urls = ["https://sannenggroup.com/shop/?sf_paged=1"]

    custom_settings = {
        "ROBOTSTXT_OBEY": False,
    }

    async def start(self):
        for url in self.start_urls:
            yield scrapy.Request(url, callback=self.parse)

    def parse(self, response):
        cards = response.css("li.product")

        if not cards:
            self.logger.warning("No product cards found on %s", response.url)
            return

        for card in cards:
            product_url = card.css("a.woocommerce-LoopProduct-link::attr(href)").get() or card.css(
                "a.ast-loop-product__link::attr(href)"
            ).get()
            if not product_url:
                continue

            name = card.css("h2.woocommerce-loop-product__title::text").get(default="").strip()
            image_url = card.css("div.astra-shop-thumbnail-wrap img::attr(data-src)").get() or card.css(
                "div.astra-shop-thumbnail-wrap img::attr(src)"
            ).get(default="")
            category = card.css("span.ast-woo-product-category::text").get(default="").strip()
            product_id = card.css("a.ast-quick-view-text::attr(data-product_id)").get(default="")
            listing_sku = self._extract_sku(name)

            yield response.follow(
                product_url,
                callback=self.parse_product,
                meta={
                    "listing_name": name,
                    "listing_image": response.urljoin(image_url) if image_url else "",
                    "listing_category": category,
                    "listing_product_id": str(product_id or ""),
                    "listing_sku": listing_sku,
                },
            )

        next_url = response.css("a.next.page-numbers::attr(href), a.next::attr(href)").get()
        if next_url:
            yield response.follow(next_url, callback=self.parse)
            return

        next_page_url = self._build_next_sfpaged_url(response.url)
        if next_page_url:
            yield scrapy.Request(next_page_url, callback=self.parse)

    def parse_product(self, response):
        page_title = response.css("title::text").get(default="").strip()
        name = response.css("h1.product_title::text").get(default="").strip() or response.meta.get("listing_name", "")

        detail_image_urls = []
        for image_url in response.css(
            "div.woocommerce-product-gallery__image a::attr(href), "
            "div.woocommerce-product-gallery__image img::attr(data-large_image), "
            "div.woocommerce-product-gallery__image img::attr(data-src), "
            "div.woocommerce-product-gallery__image img::attr(src)"
        ).getall():
            absolute = response.urljoin(image_url)
            if absolute and absolute not in detail_image_urls:
                detail_image_urls.append(absolute)

        image_url = detail_image_urls[0] if detail_image_urls else response.meta.get("listing_image", "")

        price_text = " ".join(response.css("p.price *::text, span.price *::text").getall())
        price = self._extract_price(price_text)
        if not price:
            meta_price = response.css("meta[property='product:price:amount']::attr(content)").get(default="")
            price = self._extract_price(meta_price)
        if not price:
            twitter_price = response.css("meta[name='twitter:data1']::attr(content)").get(default="")
            price = self._extract_price(twitter_price)

        description = response.css("meta[name='description']::attr(content)").get(default="").strip()
        if not description:
            description = "\n".join(
                [
                    part.strip()
                    for part in response.css("div.woocommerce-product-details__short-description *::text").getall()
                    if part and part.strip()
                ]
            )
        if not description:
            description = "\n".join(
                [
                    part.strip()
                    for part in response.css("div.woocommerce-Tabs-panel *::text").getall()
                    if part and part.strip()
                ]
            )

        sku = ""
        sku_candidates = [
            response.css("span.sku::text").get(default=""),
            response.meta.get("listing_sku", ""),
            name,
            page_title,
            response.css("meta[property='og:title']::attr(content)").get(default=""),
            response.url,
        ]

        for candidate in sku_candidates:
            sku = self._extract_sku(candidate)
            if sku:
                break

        category = self._extract_category(response) or response.meta.get("listing_category", "")
        product_id = response.meta.get("listing_product_id", "")
        if not product_id:
            parsed = urlparse(response.url)
            maybe_id = parse_qs(parsed.query).get("product_id", [""])[0]
            product_id = str(maybe_id or "")

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
            "category": category,
        }

    @staticmethod
    def _extract_price(text):
        if not text:
            return ""
        match = re.search(r"(\d[\d,]*\.?\d*)", text)
        if not match:
            return ""
        return match.group(1).replace(",", "")

    @staticmethod
    def _extract_sku(text):
        if not text:
            return ""

        value = str(text)

        prioritized = re.search(r"\b(?:SN|TIP|TS)[\s\-]*\d+[A-Z]?\b", value, re.IGNORECASE)
        if prioritized:
            return re.sub(r"[^A-Z0-9]", "", prioritized.group(0).upper())

        # Sannenggroup often uses pure numeric item code like 106010
        numeric_code = re.search(r"\b\d{5,8}\b", value)
        if numeric_code:
            return numeric_code.group(0)

        generic = re.search(r"\b[A-Z]{1,6}[\s\-]*\d{2,8}[A-Z]?\b", value, re.IGNORECASE)
        if generic:
            return re.sub(r"[^A-Z0-9]", "", generic.group(0).upper())

        return ""

    @staticmethod
    def _extract_category(response):
        crumbs = [
            text.strip()
            for text in response.css("nav.woocommerce-breadcrumb a::text, nav.woocommerce-breadcrumb span::text").getall()
            if text and text.strip()
        ]
        if not crumbs:
            return ""

        ignored = {"home", "shop", "首頁"}
        for value in reversed(crumbs):
            if value.lower() not in ignored:
                return value
        return crumbs[-1]

    @staticmethod
    def _build_next_sfpaged_url(url):
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        current_page = 1
        if "sf_paged" in query:
            try:
                current_page = int(query["sf_paged"][0])
            except (TypeError, ValueError):
                current_page = 1

        # Fallback pagination only up to a sane upper bound
        if current_page >= 100:
            return ""

        next_page = current_page + 1
        if "sf_paged" in query:
            base = re.sub(r"([?&])sf_paged=\d+", "", url)
            separator = "&" if "?" in base else "?"
            return f"{base}{separator}sf_paged={next_page}"

        separator = "&" if "?" in url else "?"
        return f"{url}{separator}sf_paged={next_page}"
