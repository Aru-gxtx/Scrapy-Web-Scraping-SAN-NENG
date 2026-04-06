import scrapy


class CooknserveSpider(scrapy.Spider):
    name = "cooknserve"
    allowed_domains = ["cooknserve.sg"]

    def start_requests(self):
        import openpyxl
        import os
        # Use workspace root for Excel file
        workspace_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
        excel_path = os.path.join(workspace_root, 'sources', 'SAN NENG.xlsx')
        wb = openpyxl.load_workbook(excel_path)
        sheet = wb.active
        skus = [row[1].value for row in sheet.iter_rows(min_row=2) if row[1].value]
        for sku in skus:
            url = f"https://cooknserve.sg/search?type=product&options%5Bprefix%5D=last&q={sku}"
            yield scrapy.Request(url, callback=self.parse_search, meta={'sku': sku})

    def parse_search(self, response):
        sku = response.meta['sku']
        # Find product links in search results
        products = response.css('div.product-item.product-item--vertical')
        for product in products:
            link = product.css('a.product-item__image-wrapper::attr(href)').get()
            if link:
                product_url = response.urljoin(link)
                yield scrapy.Request(product_url, callback=self.parse_product, meta={'sku': sku})

    def parse_product(self, response):
        sku = response.meta['sku']
        title = response.css('a.product-item__title::text').get() or response.css('h1.product-single__title::text').get()
        price = response.css('span.price::text').get()
        image = response.css('img.product-gallery__image::attr(data-zoom)').get() or response.css('img.product-gallery__image::attr(src)').get()
        yield {
            'sku': sku,
            'title': title,
            'price': price,
            'image': response.urljoin(image) if image else None,
            'url': response.url
        }
