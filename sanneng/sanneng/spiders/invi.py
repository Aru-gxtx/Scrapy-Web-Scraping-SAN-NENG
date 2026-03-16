import scrapy
import re
import json
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


class InviSpider(scrapy.Spider):
    name = "invi"
    allowed_domains = ["invi-shop.ru"]
    start_urls = ["https://invi-shop.ru/sanneng/"]
    custom_settings = {
        "ROBOTSTXT_OBEY": False,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._seen_product_urls = set()
        self._seen_search_pages = set()

    def parse(self, response):
        catalog_links = self._extract_catalog_links(response)

        if not catalog_links:
            self.logger.warning("No catalog links found on %s", response.url)

        for url in catalog_links:
            yield response.follow(url, callback=self.parse_category)

        search_url = response.urljoin("/search/?q=SN")
        yield scrapy.Request(search_url, callback=self.parse_search)

    def parse_search(self, response):
        if response.url in self._seen_search_pages:
            return
        self._seen_search_pages.add(response.url)

        context = self._extract_catalog_context(response.text)
        items = context.get("items", []) if isinstance(context, dict) else []

        for item in items:
            if not isinstance(item, dict):
                continue

            detail_page = item.get("detailPageUrl", "")
            if not detail_page:
                continue

            product_url = response.urljoin(detail_page)
            if product_url in self._seen_product_urls:
                continue
            self._seen_product_urls.add(product_url)

            listing_name = str(item.get("title", "")).strip()
            listing_code = self._extract_code(item.get("productCode", "")) or self._extract_code(listing_name)

            image_obj = item.get("image", {}) if isinstance(item.get("image"), dict) else {}
            listing_image = image_obj.get("realSrc") or image_obj.get("src") or ""

            price_obj = item.get("price", {}) if isinstance(item.get("price"), dict) else {}
            listing_price = self._normalize_price(price_obj.get("value", ""))
            listing_original_price = self._normalize_price(price_obj.get("oldValue", ""))

            yield response.follow(
                detail_page,
                callback=self.parse_product,
                meta={
                    "listing_name": listing_name,
                    "listing_code": listing_code,
                    "listing_price": listing_price,
                    "listing_original_price": listing_original_price,
                    "listing_image": response.urljoin(listing_image) if listing_image else "",
                    "listing_category": self._category_from_breadcrumbs(response),
                    "listing_product_id": str(item.get("productId", "") or ""),
                },
            )

        for page_url in self._extract_search_pagination_urls(response, context):
            if page_url not in self._seen_search_pages:
                yield scrapy.Request(page_url, callback=self.parse_search)

    def parse_category(self, response):
        context = self._extract_catalog_context(response.text)
        context_items = context.get("items", []) if isinstance(context, dict) else []

        context_product_urls = set()
        for item in context_items:
            if not isinstance(item, dict):
                continue

            detail_page = item.get("detailPageUrl", "")
            if not detail_page:
                continue

            product_url = response.urljoin(detail_page)
            context_product_urls.add(product_url)

            if product_url in self._seen_product_urls:
                continue
            self._seen_product_urls.add(product_url)

            listing_name = str(item.get("title", "")).strip()
            listing_code = self._extract_code(item.get("productCode", "")) or self._extract_code(listing_name)

            image_obj = item.get("image", {}) if isinstance(item.get("image"), dict) else {}
            listing_image = image_obj.get("realSrc") or image_obj.get("src") or ""

            price_obj = item.get("price", {}) if isinstance(item.get("price"), dict) else {}
            listing_price = self._normalize_price(price_obj.get("value", ""))
            listing_original_price = self._normalize_price(price_obj.get("oldValue", ""))

            yield response.follow(
                detail_page,
                callback=self.parse_product,
                meta={
                    "listing_name": listing_name,
                    "listing_code": listing_code,
                    "listing_price": listing_price,
                    "listing_original_price": listing_original_price,
                    "listing_image": response.urljoin(listing_image) if listing_image else "",
                    "listing_category": self._category_from_breadcrumbs(response),
                    "listing_product_id": str(item.get("productId", "") or ""),
                },
            )

        cards = response.css("div.product-card")

        for card in cards:
            product_url = card.css("a.product-card__link::attr(href)").get()
            if not product_url:
                product_url = card.css("a.link-as-card::attr(href)").get()
            if not product_url:
                continue

            absolute_product_url = response.urljoin(product_url)
            if absolute_product_url in context_product_urls:
                continue
            if absolute_product_url in self._seen_product_urls:
                continue
            self._seen_product_urls.add(absolute_product_url)

            listing_name = card.css("div.product-card__title::text").get(default="").strip()
            listing_code_raw = card.css("div.product-card__code::text").get(default="").strip()
            listing_code = self._extract_code(listing_code_raw) or self._extract_code(listing_name)

            listing_price_text = card.css("div.product-card__value::text").get(default="").strip()
            listing_price = self._normalize_price(listing_price_text)

            listing_image = card.css("img.product-card__img::attr(src)").get(default="").strip()

            yield response.follow(
                product_url,
                callback=self.parse_product,
                meta={
                    "listing_name": listing_name,
                    "listing_code": listing_code,
                    "listing_price": listing_price,
                    "listing_image": response.urljoin(listing_image) if listing_image else "",
                    "listing_category": self._category_from_breadcrumbs(response),
                },
            )

        for next_url in self._extract_pagination_links(response):
            yield response.follow(next_url, callback=self.parse_category)

    def parse_product(self, response):
        title = response.css("title::text").get(default="").strip()
        name = response.css("h1.page-title::text").get(default="").strip() or response.meta.get("listing_name", "")

        detail_image_urls = []
        for url in response.css(
            "a[data-fancybox='catalog-detail-top-slider-gallery']::attr(href), "
            "img.catalog-detail-top-slider-item__img::attr(src)"
        ).getall():
            absolute = response.urljoin(url)
            if absolute and absolute not in detail_image_urls:
                detail_image_urls.append(absolute)

        image_url = detail_image_urls[0] if detail_image_urls else response.meta.get("listing_image", "")

        price = self._normalize_price(
            response.css("div.catalog-detail-top-price-value__main::text").get(default="")
        ) or response.meta.get("listing_price", "")

        original_price = self._normalize_price(
            response.css("div.catalog-detail-top-price__old-value::text").get(default="")
        )
        if not original_price:
            original_price = response.meta.get("listing_original_price", "")

        description_parts = response.css("div.catalog-detail-tabs-panel .article *::text").getall()
        description = "\n".join([part.strip() for part in description_parts if part and part.strip()])

        code_candidates = [
            response.meta.get("listing_code", ""),
            response.css("div.catalog-detail-top-chars-item__text::text").get(default=""),
            name,
            title,
        ]

        sku = ""
        for candidate in code_candidates:
            sku = self._extract_code(candidate)
            if sku:
                break

        if not sku:
            sku = self._extract_numeric_id(response.url)

        yield {
            "name": name,
            "title": title,
            "sku": sku,
            "price": price,
            "original_price": original_price,
            "product_id": response.meta.get("listing_product_id", "") or self._extract_numeric_id(response.url),
            "product_url": response.url,
            "image_url": image_url,
            "detail_image_urls": detail_image_urls,
            "detail_image_count": len(detail_image_urls),
            "description": description,
            "brand": "SANNENG",
            "category": self._category_from_breadcrumbs(response) or response.meta.get("listing_category", ""),
        }

    @staticmethod
    def _extract_catalog_links(response):
        links = []
        href_values = response.css("a[href*='/catalog/']::attr(href)").getall()
        href_values.extend(re.findall(r'"(/catalog/[a-z0-9\-_/]+/)"', response.text, flags=re.IGNORECASE))

        for href in href_values:
            if not href:
                continue
            if href.startswith("#"):
                continue

            absolute = response.urljoin(href)
            if "/catalog/" not in absolute:
                continue
            if "/catalog/new/" in absolute:
                continue
            if absolute not in links:
                links.append(absolute)

        fallback = response.urljoin("/catalog/alyuminievye/")
        if fallback not in links:
            links.append(fallback)
        return links

    @staticmethod
    def _extract_pagination_links(response):
        links = []
        for href in response.css("div.pager a::attr(href), a.pager__link::attr(href)").getall():
            if not href:
                continue
            absolute = response.urljoin(href)
            if absolute not in links:
                links.append(absolute)
        return links

    @staticmethod
    def _extract_numeric_id(url):
        match = re.search(r"/(\d+)/?$", url or "")
        return match.group(1) if match else ""

    @staticmethod
    def _normalize_price(raw):
        if not raw:
            return ""
        cleaned = str(raw).replace("\xa0", " ").replace("₽", "").replace("/шт", "")
        cleaned = cleaned.replace("/piece", "").replace(" ", "").replace(",", ".").strip()
        match = re.search(r"\d+(?:\.\d+)?", cleaned)
        return match.group(0) if match else ""

    @staticmethod
    def _extract_code(text):
        if not text:
            return ""

        raw = str(text)
        raw = re.sub(r"(?i)\b(?:ref|арт)\s*:\s*", "", raw)

        pattern = re.compile(r"\b[A-ZА-Я]{1,6}[\s\-]*\d{2,6}[A-ZА-Я]?\b", re.IGNORECASE)
        match = pattern.search(raw)
        if not match:
            return ""

        token = match.group(0).upper().replace(" ", "")
        token = re.sub(r"[^A-Z0-9\-]", "", token)
        return token

    @staticmethod
    def _category_from_breadcrumbs(response):
        crumbs = [c.strip() for c in response.css("nav.breadcrumbs a::text").getall() if c and c.strip()]
        if not crumbs:
            return ""
        if len(crumbs) >= 2:
            return crumbs[-1]
        return crumbs[0]

    @staticmethod
    def _extract_catalog_context(text):
        if not text:
            return {}

        match = re.search(
            r"window\.catalogSectionContext\s*=\s*(\{.*?\})\s*;\s*window\['filter-endpoint'\]",
            text,
            flags=re.DOTALL,
        )
        if not match:
            return {}

        raw = match.group(1)
        try:
            return json.loads(raw)
        except Exception:
            return {}

    @staticmethod
    def _extract_search_pagination_urls(response, context):
        if not isinstance(context, dict):
            return []

        pager = context.get("pager") if isinstance(context.get("pager"), dict) else {}
        total = pager.get("total") if isinstance(pager.get("total"), int) else 0
        pager_id = str(pager.get("id") or "").strip()
        items = context.get("items") if isinstance(context.get("items"), list) else []
        page_size = len(items)

        if not pager_id or page_size <= 0 or total <= page_size:
            return []

        page_count = (total + page_size - 1) // page_size
        if page_count <= 1:
            return []

        parsed = urlparse(response.url)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))

        urls = []
        page_param = f"PAGEN_{pager_id}"
        for page in range(1, page_count + 1):
            query[page_param] = str(page)
            encoded_query = urlencode(query)
            urls.append(urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, encoded_query, parsed.fragment)))
        return urls
