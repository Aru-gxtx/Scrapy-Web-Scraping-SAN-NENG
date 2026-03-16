import scrapy
import re

try:
    from scrapy_playwright.page import PageMethod
except Exception:
    PageMethod = None


class MehsonlineSpider(scrapy.Spider):
    name = "mehsonline"
    allowed_domains = ["mehsonline.com"]
    start_urls = ["https://mehsonline.com/product-brand/san-neng/"]
    custom_settings = {
        "ROBOTSTXT_OBEY": False,
        "TWISTED_REACTOR": "twisted.internet.asyncioreactor.AsyncioSelectorReactor",
        "DOWNLOAD_HANDLERS": {
            "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
            "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
        },
        "PLAYWRIGHT_BROWSER_TYPE": "chromium",
        "PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT": 60000,
        "PLAYWRIGHT_LAUNCH_OPTIONS": {"headless": True},
    }

    async def start(self):
        for url in self.start_urls:
            yield scrapy.Request(
                url,
                callback=self.parse,
                meta=self._playwright_meta(wait_for_products=True),
            )

    def parse(self, response):
        products = response.css("section.product")

        if not products:
            self.logger.warning("No product cards found on %s", response.url)

        for product in products:
            product_url = product.css("h3.product-name a::attr(href)").get() or product.css(
                "div.thumbnail-wrapper > a::attr(href)"
            ).get()
            if not product_url:
                continue

            name = product.css("h3.product-name a::text").get(default="").strip()
            price_text = " ".join(product.css("span.price *::text").getall())
            price = self._extract_price(price_text)

            listing_image = product.css("div.thumbnail-wrapper img::attr(data-src)").get() or product.css(
                "div.thumbnail-wrapper img::attr(src)"
            ).get()

            product_id = product.attrib.get("data-product_id", "")
            sku_hint = product.css("a.add_to_cart_button::attr(data-product_sku)").get(default="")

            yield response.follow(
                product_url,
                callback=self.parse_product,
                meta={
                    "listing_name": name,
                    "listing_price": price,
                    "listing_image": response.urljoin(listing_image) if listing_image else "",
                    "listing_product_id": str(product_id or ""),
                    "listing_sku_hint": sku_hint,
                    "listing_category": self._extract_category(response),
                    **self._playwright_meta(wait_for_products=False),
                },
            )

        next_url = response.css("a.next.page-numbers::attr(href), a.next::attr(href)").get()
        if next_url:
            yield response.follow(next_url, callback=self.parse, meta=self._playwright_meta(wait_for_products=True))

    def parse_product(self, response):
        page_title = response.css("title::text").get(default="").strip()
        name = (
            response.css("h1.product_title::text").get(default="").strip()
            or response.meta.get("listing_name", "")
        )

        detail_image_urls = []
        for image_url in response.css(
            "div.woocommerce-product-gallery__image a::attr(href), "
            "div.woocommerce-product-gallery__image img::attr(data-large_image), "
            "div.woocommerce-product-gallery__image img::attr(src)"
        ).getall():
            absolute = response.urljoin(image_url)
            if absolute and absolute not in detail_image_urls:
                detail_image_urls.append(absolute)

        image_url = detail_image_urls[0] if detail_image_urls else response.meta.get("listing_image", "")

        price_text = " ".join(response.css("p.price *::text, span.price *::text").getall())
        price = self._extract_price(price_text) or response.meta.get("listing_price", "")

        description = "\n".join(
            [
                part.strip()
                for part in response.css("div.woocommerce-product-details__short-description *::text").getall()
                if part and part.strip()
            ]
        )

        category = self._extract_category(response) or response.meta.get("listing_category", "")
        product_id = response.meta.get("listing_product_id", "")

        sku_candidates = [
            response.css("span.sku::text").get(default=""),
            response.meta.get("listing_sku_hint", ""),
            name,
            page_title,
            response.url,
        ]

        sku = ""
        for candidate in sku_candidates:
            sku = self._extract_sku(candidate)
            if sku:
                break

        if not product_id:
            id_from_add_to_cart = response.css("form.cart button[name='add-to-cart']::attr(value)").get(default="")
            product_id = str(id_from_add_to_cart or "")

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
        match = re.search(r"(\d+[\d,]*\.?\d*)", text.replace("\u00a0", " "))
        if not match:
            return ""
        value = match.group(1).replace(",", "")
        return value

    @staticmethod
    def _extract_sku(text):
        if not text:
            return ""

        text = str(text)

        prioritized = re.search(r"\bSN[\s\-]*\d+[A-Z]?\b", text, flags=re.IGNORECASE)
        if prioritized:
            return re.sub(r"[^A-Z0-9]", "", prioritized.group(0).upper())

        generic = re.search(r"\b[A-Z]{1,5}[\s\-]*\d{2,7}[A-Z]?\b", text, flags=re.IGNORECASE)
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

        ignored = {"home", "products", "shop"}
        for value in reversed(crumbs):
            if value.lower() not in ignored:
                return value
        return crumbs[-1]

    @staticmethod
    def _playwright_meta(wait_for_products):
        if PageMethod is None:
            return {}

        methods = [PageMethod("wait_for_load_state", "networkidle")]
        if wait_for_products:
            methods.append(PageMethod("wait_for_selector", "section.product", timeout=45000))

        return {
            "playwright": True,
            "playwright_context": "mehsonline",
            "playwright_include_page": False,
            "playwright_page_methods": methods,
            "dont_redirect": True,
            "handle_httpstatus_all": True,
        }
