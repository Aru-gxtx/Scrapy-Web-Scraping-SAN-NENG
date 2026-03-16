import scrapy
import json
import re


class UnopanSpider(scrapy.Spider):
    name = "unopan"
    allowed_domains = ["www.unopan.tw"]
    start_urls = ["https://www.unopan.tw/search?q=SANNENG+"]
    search_query = "SANNENG "
    per_page = 50
    custom_settings = {
        "ROBOTSTXT_OBEY": False,
    }

    def parse(self, response):
        cards = response.css("div.item")

        valid_cards = []
        for card in cards:
            href = (
                card.css("a.product_image::attr(href)").get()
                or card.css("a.productClick::attr(href)").get()
                or card.css("a[href*='/products/']::attr(href)").get()
            )
            if href:
                valid_cards.append(card)

        if not valid_cards:
            yield self._build_search_api_request(response=response, page=1)
            return

        for card in valid_cards:
            href = (
                card.css("a.product_image::attr(href)").get()
                or card.css("a.productClick::attr(href)").get()
                or card.css("a[href*='/products/']::attr(href)").get()
            )

            listing_name = (
                card.css("p.product_title::text").get(default="").strip()
                or card.css("a.productClick::attr(data-name)").get(default="").strip()
            )

            listing_price = (
                card.css("span.money_tag.qk-text--discount_price::text").get(default="").strip()
                or card.css("a.productClick::attr(data-price)").get(default="").strip()
            )
            listing_original_price = card.css("del span.money_tag::text").get(default="").strip()

            style_image = card.css("a.product_image::attr(style)").get(default="")
            listing_image = self._extract_css_url(style_image)
            if not listing_image:
                listing_image = card.css("button.btn-cart::attr(data-photo)").get(default="")

            yield response.follow(
                href,
                callback=self.parse_product,
                meta={
                    "listing_name": listing_name,
                    "listing_price": listing_price,
                    "listing_original_price": listing_original_price,
                    "listing_image": self._to_absolute_url(response, listing_image),
                },
            )

        next_page = (
            response.css("a[rel='next']::attr(href)").get()
            or response.css("a.next::attr(href)").get()
            or response.css("li.next a::attr(href)").get()
        )
        if next_page:
            yield response.follow(next_page, callback=self.parse)

    def parse_search_api(self, response, page):
        try:
            data = json.loads(response.text)
        except json.JSONDecodeError:
            self.logger.error("Unopan search API returned non-JSON on page %s", page)
            return

        products_block = data.get("products") or {}
        products = products_block.get("result") or []
        total_pages = int(products_block.get("total_pages") or 0)

        for product in products:
            handle = product.get("handle", "")
            if not handle:
                continue

            featured_image = (product.get("featured_image") or {}).get("grande", "")
            variants = product.get("variants") or []
            first_variant = variants[0] if variants else {}

            listing_price = first_variant.get("price", "")
            listing_original_price = first_variant.get("compare_at_price", "")

            product_url = response.urljoin(f"/products/{handle}")
            yield scrapy.Request(
                product_url,
                callback=self.parse_product,
                meta={
                    "listing_name": product.get("title", ""),
                    "listing_price": listing_price,
                    "listing_original_price": listing_original_price,
                    "listing_image": self._to_absolute_url(response, featured_image),
                },
            )

        if total_pages and page < total_pages:
            yield self._build_search_api_request(response=response, page=page + 1)

    def parse_product(self, response):
        schema = self._extract_product_schema(response)

        title = response.css("meta[property='og:title']::attr(content)").get(default="").strip()
        if not title:
            title = response.css("title::text").get(default="").strip()

        detail_image_links = []
        for src in response.css(
            "li.product_photo img::attr(src), "
            "li.product_photo img::attr(data-src), "
            "li.swiper-slide.product_photo img::attr(src), "
            "li.swiper-slide.product_photo img::attr(data-src), "
            "img.swiper-lazy::attr(src), "
            "img.swiper-lazy::attr(data-src)"
        ).getall():
            normalized = self._to_absolute_url(response, src)
            if normalized and normalized not in detail_image_links:
                detail_image_links.append(normalized)

        og_image = self._to_absolute_url(
            response,
            response.css("meta[property='og:image']::attr(content)").get(default=""),
        )

        primary_image = ""
        if detail_image_links:
            primary_image = detail_image_links[0]
        elif schema.get("image"):
            primary_image = self._to_absolute_url(response, schema.get("image"))
        elif og_image:
            primary_image = og_image
        else:
            primary_image = response.meta.get("listing_image", "")

        if primary_image and primary_image not in detail_image_links:
            detail_image_links.append(primary_image)

        yield {
            "name": response.meta.get("listing_name") or schema.get("name", ""),
            "title": title,
            "sku": schema.get("sku", ""),
            "price": response.meta.get("listing_price") or schema.get("price", ""),
            "original_price": response.meta.get("listing_original_price", ""),
            "product_url": response.url,
            "image_url": primary_image,
            "detail_image_urls": detail_image_links,
            "detail_image_count": len(detail_image_links),
        }

    @staticmethod
    def _extract_css_url(style):
        if not style:
            return ""
        match = re.search(r"url\((['\"]?)(.*?)\1\)", style)
        return match.group(2).strip() if match else ""

    @staticmethod
    def _to_absolute_url(response, url):
        if not url:
            return ""
        if url.startswith("//"):
            return "https:" + url
        return response.urljoin(url)

    @staticmethod
    def _extract_product_schema(response):
        scripts = response.css("script[type='application/ld+json']::text").getall()
        for script in scripts:
            try:
                data = json.loads(script)
            except json.JSONDecodeError:
                continue

            candidates = data if isinstance(data, list) else [data]
            for node in candidates:
                if not isinstance(node, dict):
                    continue
                if node.get("@type") == "Product":
                    offers = node.get("offers") or {}
                    return {
                        "name": node.get("name", ""),
                        "sku": node.get("sku", "") or node.get("productId", ""),
                        "image": node.get("image", ""),
                        "price": offers.get("price", ""),
                    }

        return {}

    def _build_search_api_request(self, response, page):
        payload = {
            "q": self.search_query,
            "per": self.per_page,
            "page": page,
            "sort_by": "",
            "type": "product",
        }
        return scrapy.Request(
            url=response.urljoin("/search/search.json"),
            method="POST",
            body=json.dumps(payload),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/plain, */*",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": "https://www.unopan.tw/search?q=SANNENG+",
            },
            callback=self.parse_search_api,
            cb_kwargs={"page": page},
            dont_filter=True,
        )
