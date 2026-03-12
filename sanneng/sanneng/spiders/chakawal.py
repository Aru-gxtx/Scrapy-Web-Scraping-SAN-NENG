import scrapy


class ChakaWalSpider(scrapy.Spider):
    name = "chakawal"
    allowed_domains = ["chakawal.com"]
    start_urls = ["https://chakawal.com/product-tag/sanneng/page/1/"]

    custom_settings = {
        "ROBOTSTXT_OBEY": True,
    }

    def start_requests(self):
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://chakawal.com/",
            "Upgrade-Insecure-Requests": "1",
        }

        for url in self.start_urls:
            yield scrapy.Request(url=url, headers=headers, callback=self.parse)

    def parse(self, response):
        # Collect items from listing page, then visit detail page for richer data.
        for card in response.css("li.archive-product-container li.product"):
            item = {
                "name": card.css("h1.woocommerce-loop-product__title::text").get(default="").strip(),
                "url": card.css("a.woocommerce-LoopProduct-link::attr(href)").get(),
                "image": card.css("img.attachment-woocommerce_thumbnail::attr(src)").get(),
                "sku": card.css("a.button.product_type_simple::attr(data-product_sku)").get(),
                "category": card.css("ul.product-categories span::text").get(),
            }

            product_url = item.get("url")
            if product_url:
                yield response.follow(product_url, callback=self.parse_product, cb_kwargs={"item": item})
            else:
                yield item

        # Follow next page automatically (recommended)
        next_page = response.css("a.next.page-numbers::attr(href), a.next::attr(href)").get()
        if next_page:
            yield response.follow(next_page, callback=self.parse)

    def parse_product(self, response, item):
        gallery_nodes = response.css("div.woocommerce-product-gallery__image")

        gallery_full_image_links = self._unique(
            gallery_nodes.css("a::attr(href)").getall()
            + gallery_nodes.css("img::attr(data-large_image)").getall()
            + gallery_nodes.css("img::attr(data-src)").getall()
        )

        gallery_thumbnail_links = self._unique(gallery_nodes.css("::attr(data-thumb)").getall())
        gallery_thumb_srcsets = self._unique(gallery_nodes.css("::attr(data-thumb-srcset)").getall())

        page_title = (
            response.css("h1.product-title::text").get()
            or response.css("h1.product_title::text").get()
            or response.css("h1.entry-title::text").get()
            or response.css("meta[property='og:title']::attr(content)").get()
            or response.css("title::text").get()
            or ""
        ).strip()

        if "|" in page_title:
            page_title = page_title.split("|", 1)[0].strip()

        item["product_page_title"] = page_title
        item["gallery_full_image_links"] = gallery_full_image_links
        item["gallery_thumbnail_links"] = gallery_thumbnail_links
        item["gallery_thumb_srcsets"] = gallery_thumb_srcsets
        item["gallery_image_count"] = len(gallery_full_image_links)

        yield item

    @staticmethod
    def _unique(values):
        seen = set()
        result = []

        for value in values:
            if not value:
                continue
            if value in seen:
                continue
            seen.add(value)
            result.append(value)

        return result
