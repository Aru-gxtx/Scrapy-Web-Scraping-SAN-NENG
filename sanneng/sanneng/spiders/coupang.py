import scrapy
import re
import time
from urllib.parse import quote_plus, urljoin

from curl_cffi import requests as cffi_requests


class CoupangSpider(scrapy.Spider):
    name = "coupang"
    allowed_domains = ["www.tw.coupang.com"]
    max_pages = 27
    search_query = "SaNNeNg"
    custom_settings = {
        "ROBOTSTXT_OBEY": False,
    }

    async def start(self):
        query = getattr(self, "q", None) or self.search_query
        max_pages = int(getattr(self, "max_pages", 27) or 27)
        encoded_query = quote_plus(query)
        session = cffi_requests.Session(impersonate="chrome124")

        visited_products = set()

        for page in range(1, max_pages + 1):
            search_url = f"https://www.tw.coupang.com/np/search?q={encoded_query}&page={page}"

            try:
                resp = session.get(
                    search_url,
                    headers={"Referer": "https://www.tw.coupang.com/"},
                    timeout=45,
                )
            except Exception as exc:
                self.logger.error("Search request failed on page %d: %s", page, exc)
                break

            if resp.status_code != 200:
                self.logger.warning("Search page %d returned HTTP %s", page, resp.status_code)
                break

            selector = scrapy.Selector(text=resp.text)
            cards = selector.css("li.ProductUnit_productUnit__Qd6sv, li.search-product")
            self.logger.info("Search page %d: %d cards", page, len(cards))

            if not cards:
                break

            for card in cards:
                href = card.css("a[href*='/products/']::attr(href), a[href*='/vp/products/']::attr(href)").get()
                if not href:
                    continue

                product_url = urljoin("https://www.tw.coupang.com", href)
                product_url = product_url.split("#")[0]
                if product_url in visited_products:
                    continue
                visited_products.add(product_url)

                listing_name = (
                    card.css("div.ProductUnit_productNameV2__cV9cw::text").get(default="").strip()
                    or card.css("div.name::text").get(default="").strip()
                )
                listing_image = card.css("figure img::attr(src), img.search-product-wrap-img::attr(src), img::attr(src)").get(default="")
                price_text = "".join(
                    text.strip()
                    for text in card.css(
                        "div.custom-oos span::text, "
                        "div.PriceArea_priceArea__NntJz span::text, "
                        "strong.price-value::text, "
                        "em.sale strong::text"
                    ).getall()
                    if text.strip()
                )
                listing_price = self._extract_first_price(price_text)
                listing_original_price = "".join(card.css("del::text, del *::text, del.base-price::text").getall()).strip()
                listing_sku = self._extract_sku(listing_name, product_url)

                try:
                    product_resp = session.get(
                        product_url,
                        headers={"Referer": search_url},
                        timeout=45,
                    )
                except Exception as exc:
                    self.logger.warning("Product request failed: %s (%s)", product_url, exc)
                    continue

                if product_resp.status_code != 200:
                    self.logger.warning("Product returned HTTP %s: %s", product_resp.status_code, product_url)
                    continue

                product_selector = scrapy.Selector(text=product_resp.text)
                yield self._build_product_item(
                    selector=product_selector,
                    product_url=product_url,
                    listing_name=listing_name,
                    listing_image=listing_image,
                    listing_price=listing_price,
                    listing_original_price=listing_original_price,
                    listing_sku=listing_sku,
                )

                time.sleep(0.3)

            time.sleep(0.8)

    def _build_product_item(
        self,
        selector,
        product_url,
        listing_name,
        listing_image,
        listing_price,
        listing_original_price,
        listing_sku,
    ):
        page_title = selector.css("title::text").get(default="").strip()
        detail_image_urls = []
        for src in selector.css(
            "div.twc-relative img::attr(src), "
            "div.twc-relative img::attr(data-src), "
            "img[alt='Product image']::attr(src), "
            "img[alt='Product image']::attr(data-src), "
            "img[src*='coupangcdn.com']::attr(src)"
        ).getall():
            normalized = self._to_absolute_url(product_url, src)
            if not normalized:
                continue
            if "coupangcdn.com" not in normalized:
                continue
            if any(skip in normalized for skip in [
                "/rds/logo/",
                "/image/coupang/",
                "/image/badge/",
                "/dragonstone/",
                "/service-landing/",
                "/component_52_asset/",
                "front/front-web-next/",
                "favicon",
                "spacer",
                "noimage",
            ]):
                continue
            if normalized and normalized not in detail_image_urls:
                detail_image_urls.append(normalized)

        og_image = self._to_absolute_url(
            product_url,
            selector.css("meta[property='og:image']::attr(content)").get(default=""),
        )

        listing_image_abs = self._to_absolute_url(product_url, listing_image)
        primary_image = detail_image_urls[0] if detail_image_urls else og_image or listing_image_abs
        if primary_image and primary_image not in detail_image_urls:
            detail_image_urls.insert(0, primary_image)

        product_name = (
            selector.css("meta[property='og:title']::attr(content)").get(default="").strip()
            or listing_name
        )

        sku = listing_sku or self._extract_sku(product_name, page_title, product_url)

        return {
            "name": listing_name or product_name,
            "title": page_title,
            "sku": sku,
            "price": listing_price,
            "original_price": listing_original_price,
            "product_url": product_url,
            "image_url": primary_image,
            "detail_image_urls": detail_image_urls,
            "detail_image_count": len(detail_image_urls),
        }

    @staticmethod
    def _to_absolute_url(base_url, url):
        if not url:
            return ""
        if url.startswith("//"):
            return "https:" + url
        return urljoin(base_url, url)

    @staticmethod
    def _extract_sku(*texts):
        pattern = re.compile(r"\b(?:SN|TS|TIP)[\s\-]*\d+[A-Z]?\b", re.IGNORECASE)
        for text in texts:
            if not text:
                continue
            match = pattern.search(str(text))
            if match:
                return re.sub(r"[^A-Z0-9]", "", match.group(0).upper())
        return ""

    @staticmethod
    def _extract_first_price(text):
        if not text:
            return ""
        match = re.search(r"\$\s*([\d,]+(?:\.\d+)?)", text)
        if match:
            return match.group(1).replace(",", "")

        number_match = re.search(r"([\d,]+(?:\.\d+)?)", text)
        return number_match.group(1).replace(",", "") if number_match else ""
