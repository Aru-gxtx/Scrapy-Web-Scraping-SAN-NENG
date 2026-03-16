import scrapy
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit


class PhoonhuatSpider(scrapy.Spider):
    name = "phoonhuat"
    allowed_domains = ["www.phoonhuat.com"]
    start_urls = ["https://www.phoonhuat.com/catalogue/?s=k&keyword=SANNENG&page=1"]
    max_pages = 16

    def parse(self, response):
        products = response.css("div.product-holder")

        for product in products:
            image_url = product.css("div.product-image img::attr(src)").get(default="").strip()
            name = product.css("p.name::text").get(default="").strip()
            description = product.css("p.desc::text").get(default="").strip()
            variables = product.css("p.variables::text").get(default="").strip()
            sku = product.css("p.sku::text").get(default="").strip()
            product_id = product.css("a.product_select::attr(data-id)").get(default="").strip()

            yield {
                "name": name,
                "description": description,
                "variables": variables,
                "sku": sku,
                "product_id": product_id,
                "image_url": response.urljoin(image_url),
                "product_url": response.url,
                "page_title": response.css("title::text").get(default="").strip(),
            }

        current_page = self._current_page(response.url)
        max_pages = int(getattr(self, "max_pages", 16) or 16)
        if current_page >= max_pages:
            return

        next_url = response.css("ul.pagination a[rel='next']::attr(href)").get()
        if not next_url:
            next_url = self._build_next_page_url(response.url)

        if next_url:
            yield response.follow(next_url, callback=self.parse)

    def _build_next_page_url(self, url):
        current_page = self._current_page(url)
        max_pages = int(getattr(self, "max_pages", 16) or 16)

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
        return int((query.get("page") or ["1"])[0])
