import scrapy
import json
import re
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit


class RedmanshopSpider(scrapy.Spider):
    name = "redmanshop"
    allowed_domains = ["shop.redmanshop.com"]
    start_urls = ["https://shop.redmanshop.com/collections/vendors?page=1&q=sanneng"]
    max_pages = 200
    custom_settings = {
        "ROBOTSTXT_OBEY": False,
    }

    def parse(self, response):
        cards = response.css("div.product-item.card[data-js-product-item]")

        for card in cards:
            product_url = card.css("a.product-item__title::attr(href)").get() or card.css("a.card__image::attr(href)").get()
            if not product_url:
                continue

            name = card.css("a.product-item__title span::text").get(default="").strip()
            image_url = card.css("a.card__image img::attr(src)").get(default="").strip()
            price_texts = card.css("div.product-price span::text").getall()
            price, original_price = self._extract_prices(price_texts)

            product_id = card.css("::attr(id)").re_first(r"product-item-(\d+)") or ""

            yield response.follow(
                product_url,
                callback=self.parse_product,
                meta={
                    "listing_name": name,
                    "listing_image": self._to_absolute_url(response, image_url),
                    "listing_price": price,
                    "listing_original_price": original_price,
                    "listing_product_id": product_id,
                },
            )

        current_page = self._current_page(response.url)
        max_pages = int(getattr(self, "max_pages", 200) or 200)
        if current_page >= max_pages:
            return

        next_url = response.css("link[rel='next']::attr(href), a[rel='next']::attr(href)").get()
        if not next_url:
            next_url = self._build_next_page_url(response.url)

        if next_url:
            yield response.follow(next_url, callback=self.parse)

    def parse_product(self, response):
        schema = self._extract_product_schema(response)

        detail_image_urls = []
        for src in response.css(
            "div.product-gallery-item img::attr(src), "
            "div.product-gallery-item img::attr(data-src), "
            "meta[property='og:image']::attr(content)"
        ).getall():
            normalized = self._to_absolute_url(response, src)
            normalized = self._normalize_shopify_image_url(normalized)
            if normalized and normalized not in detail_image_urls:
                detail_image_urls.append(normalized)

        schema_image = schema.get("image")
        if isinstance(schema_image, str):
            normalized = self._normalize_shopify_image_url(self._to_absolute_url(response, schema_image))
            if normalized and normalized not in detail_image_urls:
                detail_image_urls.insert(0, normalized)
        elif isinstance(schema_image, list):
            for image_url in schema_image:
                normalized = self._normalize_shopify_image_url(self._to_absolute_url(response, image_url))
                if normalized and normalized not in detail_image_urls:
                    detail_image_urls.append(normalized)

        primary_image = detail_image_urls[0] if detail_image_urls else response.meta.get("listing_image", "")
        if primary_image and primary_image not in detail_image_urls:
            detail_image_urls.insert(0, primary_image)

        page_title = response.css("title::text").get(default="").strip()
        name = response.meta.get("listing_name") or schema.get("name") or response.css("h1::text").get(default="").strip()
        extracted_code = self._extract_catalog_code(name) or self._extract_catalog_code(page_title)
        schema_sku = str(schema.get("sku", "")).strip()

        yield {
            "name": name,
            "title": page_title,
            "sku": extracted_code or schema_sku,
            "shopify_sku": schema_sku,
            "price": schema.get("price") or response.meta.get("listing_price", ""),
            "original_price": response.meta.get("listing_original_price", ""),
            "product_id": response.meta.get("listing_product_id", ""),
            "product_url": response.url,
            "image_url": primary_image,
            "detail_image_urls": detail_image_urls,
            "detail_image_count": len(detail_image_urls),
            "description": schema.get("description", ""),
            "brand": schema.get("brand", ""),
            "category": schema.get("category", ""),
        }

    @staticmethod
    def _extract_prices(texts):
        values = []
        for text in texts:
            if not text:
                continue
            text = text.strip()
            if "$" not in text:
                continue
            cleaned = re.sub(r"[^0-9.]", "", text)
            if cleaned:
                values.append(cleaned)

        if not values:
            return "", ""
        if len(values) == 1:
            return values[0], ""
        return values[0], values[1]

    @staticmethod
    def _extract_catalog_code(text):
        if not text:
            return ""
        match = re.search(r"\b[A-Z]{2,5}[\s\-]*\d{2,6}[A-Z]?\b", str(text), re.IGNORECASE)
        if not match:
            return ""
        return re.sub(r"[^A-Z0-9]", "", match.group(0).upper())

    @staticmethod
    def _extract_product_schema(response):
        scripts = response.css("script[type='application/ld+json']::text").getall()
        for raw in scripts:
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except Exception:
                continue

            candidates = data if isinstance(data, list) else [data]
            for obj in candidates:
                if not isinstance(obj, dict):
                    continue
                if obj.get("@type") == "Product":
                    offers = obj.get("offers", {})
                    brand = obj.get("brand", {})
                    return {
                        "name": obj.get("name", ""),
                        "sku": obj.get("sku", ""),
                        "description": obj.get("description", ""),
                        "image": obj.get("image", ""),
                        "category": obj.get("category", ""),
                        "brand": brand.get("name", "") if isinstance(brand, dict) else str(brand or ""),
                        "price": offers.get("price", "") if isinstance(offers, dict) else "",
                    }
        return {}

    @staticmethod
    def _to_absolute_url(response, url):
        if not url:
            return ""
        if url.startswith("//"):
            return "https:" + url
        return response.urljoin(url)

    @staticmethod
    def _normalize_shopify_image_url(url):
        if not url:
            return ""
        return re.sub(r"([?&])width=\d+", "", url)

    def _build_next_page_url(self, url):
        current_page = self._current_page(url)
        max_pages = int(getattr(self, "max_pages", 200) or 200)
        if current_page >= max_pages:
            return ""

        split = urlsplit(url)
        query = parse_qs(split.query)
        query["page"] = [str(current_page + 1)]
        next_query = urlencode(query, doseq=True)
        return urlunsplit((split.scheme, split.netloc, split.path, next_query, split.fragment))

    @staticmethod
    def _current_page(url):
        split = urlsplit(url)
        query = parse_qs(split.query)
        if query.get("page"):
            try:
                return int(query["page"][0])
            except Exception:
                return 1
        return 1
