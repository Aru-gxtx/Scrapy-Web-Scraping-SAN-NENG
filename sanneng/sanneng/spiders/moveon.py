import scrapy
import re
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

try:
    from scrapy_playwright.page import PageMethod
except Exception:
    PageMethod = None


class MoveonSpider(scrapy.Spider):
    name = "moveon"
    allowed_domains = ["moveon.global"]
    start_urls = ["https://moveon.global/BD_en/product-list?region_locale=BD_en&idEndPart_slug=ADMXQT0MDQ203-sanneng-baking-mold-square-ring-4-6-8-10-12-14inch-square-heightened-mousse-ring-cake-cutting-mold&idFirstPart=01JPFWTQT23CW&page=1&per_page=40&keyword=SANNENG&browser=true"]

    custom_settings = {
        "ROBOTSTXT_OBEY": False,
        "TWISTED_REACTOR": "twisted.internet.asyncioreactor.AsyncioSelectorReactor",
        "DOWNLOAD_HANDLERS": {
            "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
            "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
        },
        "PLAYWRIGHT_BROWSER_TYPE": "chromium",
        "PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT": 120000,
        "PLAYWRIGHT_LAUNCH_OPTIONS": {"headless": True},
    }

    async def start(self):
        for url in self.start_urls:
            yield scrapy.Request(url, callback=self.parse, meta=self._playwright_meta(wait_for_listing=True))

    def parse(self, response):
        cards = response.css("a[href*='/products/']")
        seen_urls = set()
        yielded = 0

        for card in cards:
            href = card.css("::attr(href)").get()
            if not href:
                continue

            product_url = response.urljoin(href)
            if product_url in seen_urls:
                continue
            seen_urls.add(product_url)

            listing_title = " ".join(card.css("h1::text, h2::text, h3::text, p::text").getall()).strip()
            if not listing_title:
                continue

            image_candidates = [
                response.urljoin(src)
                for src in card.css("img::attr(src)").getall()
                if src and "placeholderImageSquare" not in src
            ]
            listing_image = image_candidates[0] if image_candidates else ""

            price_text = " ".join(card.css("*::text").getall())
            listing_price = self._extract_price(price_text)

            sku_hint = self._extract_sku(f"{listing_title} {product_url}")
            product_id = self._extract_product_id_from_url(product_url)

            yielded += 1
            yield response.follow(
                product_url,
                callback=self.parse_product,
                meta={
                    "listing_name": listing_title,
                    "listing_image": listing_image,
                    "listing_price": listing_price,
                    "listing_sku_hint": sku_hint,
                    "listing_product_id": product_id,
                    "listing_category": self._extract_category_from_listing(response),
                    **self._playwright_meta(wait_for_listing=False),
                },
            )

        if yielded == 0:
            self.logger.warning("No listing cards found on %s", response.url)
            return

        next_page_url = self._build_next_page_url(response.url)
        if next_page_url:
            yield scrapy.Request(next_page_url, callback=self.parse, meta=self._playwright_meta(wait_for_listing=True))

    def parse_product(self, response):
        page_title = response.css("title::text").get(default="").strip()
        name = response.css("h1::text").get(default="").strip() or response.meta.get("listing_name", "")

        description = response.css("meta[name='description']::attr(content)").get(default="").strip()
        if not description:
            description = " ".join(
                [
                    part.strip()
                    for part in response.css("main *::text").getall()
                    if part and part.strip()
                ]
            )

        detail_image_urls = []

        image_selectors = [
            "main img::attr(src)",
            "main img::attr(data-src)",
            "main img::attr(data-original)",
        ]
        for selector in image_selectors:
            for src in response.css(selector).getall():
                if not src:
                    continue
                absolute = response.urljoin(src)
                if "placeholderImageSquare" in absolute:
                    continue
                if absolute.endswith(".svg"):
                    continue
                if absolute not in detail_image_urls:
                    detail_image_urls.append(absolute)

        detail_video_urls = []
        detail_video_poster_urls = []

        for src in response.css("video source::attr(src), video::attr(src)").getall():
            if not src:
                continue
            absolute = response.urljoin(src)
            if absolute not in detail_video_urls:
                detail_video_urls.append(absolute)

        for poster in response.css("video::attr(poster)").getall():
            if not poster:
                continue
            absolute = response.urljoin(poster)
            if absolute not in detail_video_poster_urls:
                detail_video_poster_urls.append(absolute)
            if absolute not in detail_image_urls:
                detail_image_urls.append(absolute)

        image_url = detail_image_urls[0] if detail_image_urls else response.meta.get("listing_image", "")

        price_text = " ".join(response.css("main *::text").getall())
        price = self._extract_price(price_text) or response.meta.get("listing_price", "")

        category = self._extract_category(response) or response.meta.get("listing_category", "")
        product_id = response.meta.get("listing_product_id") or self._extract_product_id_from_url(response.url)

        sku_candidates = [
            response.meta.get("listing_sku_hint", ""),
            name,
            page_title,
            description,
            response.url,
        ]

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
            "detail_video_urls": detail_video_urls,
            "detail_video_poster_urls": detail_video_poster_urls,
            "description": description,
            "brand": "SANNENG",
            "category": category,
        }

    @staticmethod
    def _extract_price(text):
        if not text:
            return ""
        match = re.search(r"(?:৳|BDT\s*)?(\d[\d,]*\.?\d*)", str(text).replace("\u00a0", " "))
        if not match:
            return ""
        return match.group(1).replace(",", "")

    @staticmethod
    def _extract_sku(text):
        if not text:
            return ""

        value = str(text)

        prioritized = re.search(r"\b(?:SN|UN|TIP|TS)[\s\-]*\d+[A-Z]?\b", value, re.IGNORECASE)
        if prioritized:
            return re.sub(r"[^A-Z0-9]", "", prioritized.group(0).upper())

        generic = re.search(r"\b[A-Z]{1,5}[\s\-]*\d{2,8}[A-Z]?\b", value, re.IGNORECASE)
        if generic:
            return re.sub(r"[^A-Z0-9]", "", generic.group(0).upper())

        return ""

    @staticmethod
    def _extract_category(response):
        crumb_text = [
            text.strip()
            for text in response.css("nav a::text, nav span::text, ol li::text, ul li::text").getall()
            if text and text.strip()
        ]
        ignored = {"home", "products", "product details", "moveon"}
        for value in reversed(crumb_text):
            if value.lower() not in ignored and len(value) > 1:
                return value
        return ""

    @staticmethod
    def _extract_category_from_listing(response):
        keyword = parse_qs(urlparse(response.url).query).get("keyword", [""])[0]
        return keyword.strip().upper() if keyword else ""

    @staticmethod
    def _extract_product_id_from_url(url):
        segments = [segment for segment in urlparse(url).path.split("/") if segment]
        if not segments:
            return ""
        return segments[-1]

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

        if current_page >= 200:
            return ""

        query["page"] = [str(current_page + 1)]
        next_query = urlencode(query, doseq=True)
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, next_query, parsed.fragment))

    @staticmethod
    def _playwright_meta(wait_for_listing):
        if PageMethod is None:
            return {}

        methods = [
            PageMethod("wait_for_load_state", "domcontentloaded"),
            PageMethod("wait_for_timeout", 3000),
        ]
        if wait_for_listing:
            methods.append(PageMethod("wait_for_selector", "a[href*='/products/']", timeout=45000))
        else:
            methods.append(PageMethod("wait_for_selector", "main", timeout=45000))

        return {
            "playwright": True,
            "playwright_context": "moveon",
            "playwright_include_page": False,
            "playwright_page_methods": methods,
            "dont_redirect": True,
            "handle_httpstatus_all": True,
        }
