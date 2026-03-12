import json
import re

import scrapy


class SannengvietnamSpider(scrapy.Spider):
    name = "sannengvietnam"
    allowed_domains = ["sannengvietnam.com"]

    BASE_URL = "https://sannengvietnam.com"

    async def start(self):
        yield scrapy.Request(
            f"{self.BASE_URL}/collections/all?page=1",
            callback=self.parse,
            meta={"page": 1},
        )

    def parse(self, response):
        page = response.meta["page"]

        cards = response.css("div.product-block.product-resize")
        if not cards:
            return  # No products on this page — done paginating

        for card in cards:
            rel_url = card.css("a.image-resize::attr(href)").get("")
            name = card.css("h3.pro-name a::text").get("").strip()
            price = card.css("span.pro-price::text").get("").strip()
            listing_img = card.css("img.img-loop::attr(src)").get("") or \
                          card.css("img.img-loop::attr(data-src)").get("")

            if not rel_url:
                continue

            full_url = self.BASE_URL + rel_url if rel_url.startswith("/") else rel_url

            # Best-effort SKU from listing name before hitting detail page
            sku_match = re.search(r"\bSN\d+\b", name, re.IGNORECASE)
            sku = sku_match.group(0).upper() if sku_match else ""

            # Discard lazy-load base64 placeholders
            if listing_img and listing_img.startswith("data:"):
                listing_img = ""
            elif listing_img and listing_img.startswith("//"):
                listing_img = "https:" + listing_img

            yield scrapy.Request(
                full_url,
                callback=self.parse_product,
                meta={
                    "name": name,
                    "price": price,
                    "sku": sku,
                    "listing_image": listing_img,
                    "url": full_url,
                },
            )

        # Follow next page
        yield scrapy.Request(
            f"{self.BASE_URL}/collections/all?page={page + 1}",
            callback=self.parse,
            meta={"page": page + 1},
        )

    def parse_product(self, response):
        # --- Gallery images ---
        gallery_images = []
        for img in response.css("li.product-gallery-item img.product-image-feature"):
            src = img.attrib.get("src", "").strip()
            if src:
                if src.startswith("//"):
                    src = "https:" + src
                if src not in gallery_images:
                    gallery_images.append(src)

        listing_fallback = response.meta.get("listing_image", "")
        # Prefer highest-quality master image from gallery; only fall back to
        # listing thumbnail if the gallery yielded nothing
        primary_image = gallery_images[0] if gallery_images else listing_fallback

        # --- Title ---
        page_title = response.css("div.product-title h1::text").get("").strip()
        if not page_title:
            page_title = response.css("h1::text").get("").strip()

        # --- Parse embedded `var meta = {...}` for category, price, type ---
        meta_raw = response.css("script").re_first(r"var meta\s*=\s*(\{.*?\});")
        category = ""
        price_vnd = response.meta.get("price", "")
        try:
            if meta_raw:
                meta_obj = json.loads(meta_raw)
                product_meta = meta_obj.get("product", {})
                category = product_meta.get("type", "")
                if not price_vnd:
                    raw_price = product_meta.get("price", "")
                    if raw_price:
                        price_vnd = f"{int(raw_price):,}₫"
        except (json.JSONDecodeError, ValueError):
            pass

        # --- SKU: prefer listing-extracted; fallback to description meta ---
        sku = response.meta.get("sku", "")
        if not sku:
            desc = response.css("meta[name='description']::attr(content)").get("")
            m = re.search(r"Mã sản phẩm:\s*(SN\d+)", desc, re.IGNORECASE)
            if m:
                sku = m.group(1).upper()
            else:
                m = re.search(r"\bSN\d+\b", page_title, re.IGNORECASE)
                if m:
                    sku = m.group(0).upper()

        yield {
            "name": response.meta.get("name") or page_title,
            "url": response.meta["url"],
            "sku": sku,
            "price": price_vnd,
            "image": primary_image,
            "category": category,
            "page_title": page_title,
            "gallery_images": gallery_images,
            "gallery_image_count": len(gallery_images),
        }

