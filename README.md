# Scrapy Web Scraping SAN NENG

## XLSX Image Link checker (Column E)

Use this script to read `Image Link` from column E and download images for manual checking:

```bash
python xlsx_download_images.py
```

Useful options:

```bash
python xlsx_download_images.py --xlsx "sources/SAN NENG.xlsx" --column E --out-dir downloads/image_check
python xlsx_download_images.py --limit 50 --retries 3 --timeout 30
python xlsx_download_images.py --overwrite
```

Output:
- Downloaded files are saved to `downloads/image_check` (or `--out-dir`).
- A report is saved as `download_report.csv` in the same output folder.

