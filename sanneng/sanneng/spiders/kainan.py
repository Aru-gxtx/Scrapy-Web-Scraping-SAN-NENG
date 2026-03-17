import scrapy


class KainanSpider(scrapy.Spider):
    name = "kainan"
    allowed_domains = ["www.kainan-food.com.tw"]
    start_urls = ["https://www.kainan-food.com.tw/cht/productm/showlist-6114/pages=1"]
    custom_settings = {
        'CLOSESPIDER_PAGECOUNT': 0,  # Remove page limit for full crawl
    }

    def start_requests(self):
        search_mode = getattr(self, 'search_mode', None)
        if search_mode:
            # Search mode: read SKUs from Excel and yield search requests
            import openpyxl
            wb = openpyxl.load_workbook('sources/SAN NENG.xlsx')
            sheet = wb.active
            skus = [row[1].value for row in sheet.iter_rows(min_row=2) if row[1].value]
            for sku in skus:
                search_url = f"https://www.kainan-food.com.tw/cht/productm/showlist-6114/search?keyword={sku}"
                yield scrapy.Request(search_url, callback=self.parse_search, meta={'search_sku': sku})
        else:
            # Default mode: listing crawl
            for url in self.start_urls:
                yield scrapy.Request(url, callback=self.parse)


    def parse(self, response):
        # Extract product cards
        products = response.css('li > a[href*="pageinfo-"]')
        found_any = False
        for product in products:
            url = response.urljoin(product.attrib['href'])
            img = product.css('div.pic img::attr(src)').get()
            name = product.css('h3::text').get()
            price = product.xpath('../../div[@class="price"]/span/text()').get()

            found_any = True
            yield scrapy.Request(
                url,
                callback=self.parse_product,
                meta={
                    'listing_img': img,
                    'listing_name': name,
                    'listing_price': price,
                    'listing_url': url,
                }
            )

        # Pagination: increment pages= parameter
        if found_any:
            import re
            current_page = 1
            m = re.search(r'pages=(\d+)', response.url)
            if m:
                current_page = int(m.group(1))
            next_page = current_page + 1
            next_url = re.sub(r'pages=\d+', f'pages={next_page}', response.url)
            if next_url == response.url:
                # If not found, append pages param
                if '?' in response.url:
                    next_url = response.url + f'&pages={next_page}'
                else:
                    next_url = response.url + f'?pages={next_page}'
            yield scrapy.Request(next_url, callback=self.parse)

    def parse_search(self, response):
        # Search mode: parse search results for SKU
        products = response.css('li > a[href*="pageinfo-"]')
        for product in products:
            url = response.urljoin(product.attrib['href'])
            img = product.css('div.pic img::attr(src)').get()
            name = product.css('h3::text').get()
            price = product.xpath('../../div[@class="price"]/span/text()').get()
            yield scrapy.Request(
                url,
                callback=self.parse_product,
                meta={
                    'listing_img': img,
                    'listing_name': name,
                    'listing_price': price,
                    'listing_url': url,
                    'search_sku': response.meta.get('search_sku'),
                }
            )

    def parse_product(self, response):
        # Gallery images
        gallery_imgs = response.css('li.flex-active-slide div.pic img::attr(src)').getall()
        if not gallery_imgs:
            # fallback: all images in gallery
            gallery_imgs = response.css('div.pic img::attr(src)').getall()

        # Product name
        name = response.css('h3::text').get() or response.meta.get('listing_name')

        # SKU extraction from title or description
        sku = ''
        title = response.css('title::text').get()
        if title:
            import re
            sku_match = re.findall(r'SN\d{4}', title)
            if sku_match:
                sku = ','.join(sku_match)

        # Description
        desc = response.css('meta[name="description"]::attr(content)').get()

        # Price
        price = response.meta.get('listing_price')

        # Main image
        main_img = response.meta.get('listing_img')

        yield {
            'name': name,
            'sku': sku,
            'price': price,
            'product_url': response.url,
            'image_url': main_img,
            'gallery_images': gallery_imgs,
            'description': desc,
        }
