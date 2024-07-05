import csv
import os

from selenium import webdriver
from selenium.webdriver.common.by import By


def sanitize(table_data):
    table_data = [row for row in table_data if len(row) > 1]

    while True:
        empty_col_index = -1
        for i in range(0, len(table_data[0])):
            if table_data[0][i] == "" or table_data[0][i] is None:
                empty_col_index = i
                break
        if empty_col_index < 0:
            break
        table_data = [
            row[:empty_col_index] + row[empty_col_index + 1 :] for row in table_data
        ]

    return table_data


def _get_data(url):
    driver = webdriver.Chrome()
    try:
        driver.get(url)
        table = driver.find_element(By.XPATH, "//table")
        table_data = []
        rows = table.find_elements(By.TAG_NAME, "tr")
        for row in rows:
            cells = row.find_elements(By.TAG_NAME, "th")
            if len(cells) > 0:
                row_data = [cell.text for cell in cells]
                table_data.append(row_data)
                continue

            cells = row.find_elements(By.TAG_NAME, "td")
            row_data = [cell.text for cell in cells]
            table_data.append(row_data)
        return table_data
    except Exception as e:
        raise e
    finally:
        driver.quit()


def _collect(i):
    file_name = f"./data/marketcap_{i}.csv"
    if os.path.exists(file_name):
        return
    table_data = sanitize(_get_data(f"https://www.coingecko.com/?page={i}&items=300"))
    with open(file_name, "w") as f:
        w = csv.writer(f)
        w.writerows(table_data)


def _merge(count, out):
    data = []
    for i in range(1, count):
        file_name = f"./data/marketcap_{i}.csv"
        with open(file_name, "r") as f:
            first_row = True
            for row in csv.reader(f):
                if first_row:
                    row = row[0:2] + ["Symbol"] + row[2:]
                    first_row = False
                    if i > 1:
                        continue
                else:
                    name = row[1].split(" ")
                    symbol = name[len(name) - 1]
                    name = row[1].removesuffix(" " + symbol)
                    row = row[0:2] + [symbol] + row[2:]
                    row[1] = name
                if row[0] == "":
                    break
                data.append(row)
        data.sort(key=lambda row: -1 if row[0] == "#" else int(row[0]))
    with open(out, "w") as fw:
        w = csv.writer(fw)
        w.writerows(data)


def _main():
    out = "./data/marketcap.csv"
    if os.path.exists(out):
        return
    for i in range(1, 17):
        _collect(i)
    _merge(17, out)


if __name__ == "__main__":
    _main()
