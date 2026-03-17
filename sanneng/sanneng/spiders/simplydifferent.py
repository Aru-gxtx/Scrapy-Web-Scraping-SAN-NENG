import scrapy


class SimplydifferentSpider(scrapy.Spider):
    name = "simplydifferent"
    allowed_domains = ["www.simplydifferent.in"]

    def start_requests(self):
        import openpyxl
        import os
        # Find the absolute path to the workspace root
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
        xlsx_path = os.path.join(root, 'sources', 'SAN NENG.xlsx')
        wb = openpyxl.load_workbook(xlsx_path)
        sheet = wb.active
        skus = [row[1].value for row in sheet.iter_rows(min_row=2) if row[1].value]
        for sku in skus:
            url = f"https://www.simplydifferent.in/search?q={sku}"
            yield scrapy.Request(url, callback=self.parse_search, meta={'sku': sku})

    def parse_search(self, response):
        # Find product card in search results
        product_link = response.css('div.grid__item.one-fifth a::attr(href)').get()
        if not product_link:
            self.logger.info(f"No product found for SKU {response.meta['sku']}")
            return
        url = response.urljoin(product_link)
        yield scrapy.Request(url, callback=self.parse_product, meta={'sku': response.meta['sku']})

    def parse_product(self, response):
        search_sku = response.meta['sku']
        # Title
        title = response.css('h1.product-single__title::text').get()
        # Description
        desc = response.css('div.product-description.rte').xpath('string()').get()
        # Main image
        img = response.css('img.product-single__image::attr(src)').get()
        if img:
            img = response.urljoin(img)
        # Gallery images
        gallery = response.css('ul.gallery li::attr(data-mfp-src)').getall()
        gallery = [response.urljoin(g) for g in gallery if g]

        # Parse variants from select options
        variants = response.css('select.product-single__variants option')
        for option in variants:
            variant_sku = option.attrib.get('data-sku')
            variant_text = option.xpath('text()').get()
            price_match = None
            if variant_text:
                # Extract price from option text
                import re
                price_match = re.search(r'Rs\.\s*([\d,.]+)', variant_text)
            price = price_match.group(1) if price_match else None
            # Only yield if SKU matches search_sku
            if variant_sku and variant_sku == search_sku:
                yield {
                    'sku': variant_sku,
                    'title': title.strip() if title else None,
                    'variant': variant_text.strip() if variant_text else None,
                    'price': price,
                    'description': desc.strip() if desc else None,
                    'image': img,
                    'gallery': gallery,
                    'url': response.url,
                }
