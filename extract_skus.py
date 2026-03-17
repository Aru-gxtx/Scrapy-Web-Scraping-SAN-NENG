import openpyxl

# Load workbook and sheet
wb = openpyxl.load_workbook('sources/SAN NENG.xlsx')
sheet = wb.active

# Extract SKUs from column B (skip header)
skus = [row[1].value for row in sheet.iter_rows(min_row=2) if row[1].value]

# Print SKUs for verification
for sku in skus:
    print(sku)
