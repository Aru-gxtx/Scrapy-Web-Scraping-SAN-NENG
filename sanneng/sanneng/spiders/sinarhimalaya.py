import scrapy
import json
import re
import time
from urllib.parse import quote_plus, urljoin

from curl_cffi import requests as cffi_requests


class SinarhimalayaSpider(scrapy.Spider):
    name = "sinarhimalaya"
    allowed_domains = ["sinarhimalaya.com"]
    start_urls = ["https://sinarhimalaya.com/page/1/?post_type=product&s=SANNENG"]
    max_pages = 157
    search_query = "SANNENG"
    custom_settings = {
        "ROBOTSTXT_OBEY": False,
    }

    async def start(self):
        query = getattr(self, "q", None) or self.search_query
        max_pages = int(getattr(self, "max_pages", 157) or 157)
        encoded_query = quote_plus(query)

        session = cffi_requests.Session(impersonate="chrome124")
        visited = set()

        for page in range(1, max_pages + 1):
            listing_url = f"https://sinarhimalaya.com/page/{page}/?post_type=product&s={encoded_query}"
            try:
                listing_resp = session.get(
                    listing_url,
                    headers={"Referer": "https://sinarhimalaya.com/"},
                    timeout=45,
                )
            except Exception as exc:
                self.logger.error("Listing request failed page %d: %s", page, exc)
                break

            if listing_resp.status_code != 200:
                self.logger.warning("Listing page %d returned HTTP %s", page, listing_resp.status_code)
                break

            selector = scrapy.Selector(text=listing_resp.text)
            products = selector.css("li.isotope-item.product, li.product")
            self.logger.info("Listing page %d: %d products", page, len(products))
            if not products:
                break

            for product in products:
                product_url = product.css("h4.mfn-woo-product-title a::attr(href)").get()
                if not product_url:
                    product_url = product.css("div.image_wrapper > a::attr(href)").get()
                if not product_url:
                    continue

                if product_url in visited:
                    continue
                visited.add(product_url)

                listing_name = product.css("h4.mfn-woo-product-title a::text").get(default="").strip()
                listing_image = product.css("div.image_wrapper img::attr(src)").get(default="").strip()
                listing_sku = self._extract_listing_sku(product)
                listing_product_id = product.css("input.pmwProductId::attr(data-id)").get(default="").strip()

                try:
                    detail_resp = session.get(
                        product_url,
                        headers={"Referer": listing_url},
                        timeout=45,
                    )
                except Exception as exc:
                    self.logger.warning("Detail request failed: %s (%s)", product_url, exc)
                    continue

                if detail_resp.status_code != 200:
                    self.logger.warning("Detail returned HTTP %s: %s", detail_resp.status_code, product_url)
                    continue

                detail_selector = scrapy.Selector(text=detail_resp.text)
                yield self._build_detail_item(
                    selector=detail_selector,
                    product_url=product_url,
                    listing_name=listing_name,
                    listing_image=listing_image,
                    listing_sku=listing_sku,
                    listing_product_id=listing_product_id,
                )

                time.sleep(0.2)

            time.sleep(0.5)

    def _build_detail_item(self, selector, product_url, listing_name, listing_image, listing_sku, listing_product_id):
        schema = self._extract_product_schema(selector)

        detail_image_urls = []
        for src in selector.css(
            "figure.woocommerce-product-gallery__wrapper div.woocommerce-product-gallery__image a::attr(href), "
            "figure.woocommerce-product-gallery__wrapper img::attr(data-large_image), "
            "figure.woocommerce-product-gallery__wrapper img::attr(src)"
        ).getall():
            normalized = self._to_absolute_url(product_url, src)
            if normalized and normalized not in detail_image_urls:
                detail_image_urls.append(normalized)

        primary_image = (
            detail_image_urls[0]
            if detail_image_urls
            else self._to_absolute_url(product_url, listing_image)
        )

        if primary_image and primary_image not in detail_image_urls:
            detail_image_urls.insert(0, primary_image)

        return {
            "name": listing_name or schema.get("name") or selector.css("h1.product_title::text").get(default="").strip(),
            "title": selector.css("title::text").get(default="").strip(),
            "sku": listing_sku or schema.get("sku") or self._extract_sku_text(selector.css("h1.product_title::text").get(default="")),
            "price": schema.get("price", ""),
            "original_price": "",
            "product_id": listing_product_id,
            "product_url": product_url,
            "image_url": primary_image,
            "detail_image_urls": detail_image_urls,
            "detail_image_count": len(detail_image_urls),
        }

    def _extract_listing_sku(self, product):
        script_texts = product.css("script::text").getall()
        pattern = re.compile(r'"sku"\s*:\s*"([^\"]+)"', re.IGNORECASE)
        for script in script_texts:
            match = pattern.search(script or "")
            if match:
                return match.group(1).strip()

        name = product.css("h4.mfn-woo-product-title a::text").get(default="")
        return self._extract_sku_text(name)

    @staticmethod
    def _extract_sku_text(text):
        if not text:
            return ""
        match = re.search(r"\b(?:SN|U\d|GA|TS|TIP)[\.\-\s]*[A-Z0-9\.\-]+\b", str(text), re.IGNORECASE)
        return match.group(0).strip() if match else ""

    @staticmethod
    def _to_absolute_url(base_url, url):
        if not url:
            return ""
        if url.startswith("//"):
            return "https:" + url
        return urljoin(base_url, url)

    @staticmethod
    def _extract_product_schema(selector):
        scripts = selector.css("script[type='application/ld+json']::text").getall()
        for script in scripts:
            try:
                data = json.loads(script)
            except Exception:
                continue

            candidates = data if isinstance(data, list) else [data]
            for node in candidates:
                if not isinstance(node, dict):
                    continue
                if node.get("@type") == "Product":
                    offers = node.get("offers") or {}
                    price = ""
                    if isinstance(offers, dict):
                        price = offers.get("price", "")
                    return {
                        "name": node.get("name", ""),
                        "sku": node.get("sku", ""),
                        "price": price,
                    }

        return {}
