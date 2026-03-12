# boe_loader.py
# FINAL PERFECT VERSION – shows total rows + live % progress

import xml.etree.ElementTree as ET
import psycopg2
import os
import sys
import shutil
from datetime import datetime

def get_db_connection():
    """Use DB_* environment variables (same as api/db_connect.py)."""
    return psycopg2.connect(
        dbname=os.environ.get("DB_NAME", "postgres"),
        user=os.environ.get("DB_USER", "postgres"),
        password=os.environ.get("DB_PASS", ""),
        host=os.environ.get("DB_HOST", "localhost"),
        port=os.environ.get("DB_PORT", "5432"),
    )

# ------------------------------------------------------------------
XML_INPUT_DIR     = "boe_header_load"
XML_PROCESSED_DIR = "boe_header_processed"
XML_ERROR_DIR     = "boe_header_error"

os.makedirs(XML_PROCESSED_DIR, exist_ok=True)
os.makedirs(XML_ERROR_DIR,     exist_ok=True)

NS = {'def': 'http://developer.cognos.com/schemas/xmldata/1/'}

INSERT_SQL = """
INSERT INTO boe_header (
    declaration_date, boe_approval_date, regime, boe_no, bl_number,
    importer_tin, importer_name, importer_address,
    consignee_tin, consignee_name, consignee_address,
    item_hs_code, no_of_pkg, package_unit_cd, item_description,
    item_origin_country, zone, cpc, gross_weight, net_weight,
    port_of_loading, vessel_carrier, discharge_terminal,
    shipping_line_name, cargo_type, package_type,
    gate_out_confirmation_date, final_date_of_discharge,
    country_of_shipment, port_of_discharge, ingested_at
) VALUES (%s,%s,%s,%s,%s, %s,%s,%s,%s,%s, %s,%s,%s,%s,%s, %s,%s,%s,%s,%s, %s,%s,%s,%s,%s, %s,%s,%s,%s,%s, %s)
"""

def parse_iso_datetime(text):
    if not text or not text.strip():
        return None
    text = text.strip()
    try:
        return datetime.fromisoformat(text.replace('Z', '+00:00'))
    except:
        try:
            return datetime.strptime(text, '%Y-%m-%d %H:%M:%S')
        except:
            return None

def safe_int(x):   return int(float(x)) if x and str(x).strip() else 0
def safe_float(x): return float(x) if x and str(x).strip() else None

# ------------------------------------------------------------------
# COUNT ROWS FIRST – VERY FAST
# ------------------------------------------------------------------
def count_xml_rows(file_path: str) -> int:
    print("  Counting total rows (this takes 5–15 seconds on large files)... ", end="", flush=True)
    count = 0
    for _, elem in ET.iterparse(file_path, events=('end',)):
        if elem.tag.endswith('row'):
            count += 1
        elem.clear()
    print(f"{count:,} rows")
    return count

# ------------------------------------------------------------------
# MAIN STREAMING LOADER WITH PROGRESS BAR
# ------------------------------------------------------------------
def stream_and_load(file_path: str):
    total_rows = count_xml_rows(file_path)
    if total_rows == 0:
        print("  No rows found!")
        return False

    print(f"  → Loading {total_rows:,} records → 0%", end="", flush=True)

    conn = get_db_connection()
    cur = conn.cursor()
    batch = []
    batch_size = 10000
    loaded = 0

    try:
        for event, elem in ET.iterparse(file_path, events=('end',)):
            if elem.tag.endswith('row'):
                values = []
                for v in elem.iterfind('def:value', NS):
                    if v.get('{http://www.w3.org/2001/XMLSchema-instance}nil') == 'true':
                        values.append(None)
                    else:
                        values.append(v.text)

                if len(values) < 30:
                    elem.clear()
                    continue

                record = (
                    parse_iso_datetime(values[0]), parse_iso_datetime(values[1]), values[2], values[3], values[4],
                    values[5], values[6], values[7], values[8], values[9],
                    values[10], values[11], safe_int(values[12]), values[13], values[14],
                    values[15], values[16], values[17], safe_float(values[18]), safe_float(values[19]),
                    values[20], values[21], values[22], values[23], values[24],
                    values[25], parse_iso_datetime(values[26]), parse_iso_datetime(values[27]),
                    values[28], values[29], datetime.now()
                )
                batch.append(record)

                if len(batch) >= batch_size:
                    cur.executemany(INSERT_SQL, batch)
                    loaded += len(batch)
                    percentage = (loaded / total_rows) * 100
                    print(f"\r  → Loading {total_rows:,} records → {percentage:6.2f}% ({loaded:,} rows)", end="", flush=True)
                    batch.clear()

                elem.clear()

        # Final batch
        if batch:
            cur.executemany(INSERT_SQL, batch)
            loaded += len(batch)

        conn.commit()
        print(f"\r  → Loading {total_rows:,} records → 100.00% ({loaded:,} rows) → DONE")
        return True

    except Exception as e:
        conn.rollback()
        print(f"\n  FAILED: {e}")
        return False
    finally:
        cur.close()
        conn.close()

# ------------------------------------------------------------------
# MAIN
# ------------------------------------------------------------------
def main():
    files = sorted([f for f in os.listdir(XML_INPUT_DIR) if f.lower().endswith('.xml')])
    if not files:
        print("No XML files found.")
        return

    print(f"Starting load of {len(files)} file(s)...\n")
    success = failed = 0

    for f in files:
        path = os.path.join(XML_INPUT_DIR, f)
        print(f"→ {f}")
        if stream_and_load(path):
            shutil.move(path, os.path.join(XML_PROCESSED_DIR, f))
            success += 1
        else:
            shutil.move(path, os.path.join(XML_ERROR_DIR, f))
            failed += 1
        print()

    print(f"ALL DONE | Success: {success} | Failed: {failed}")

if __name__ == "__main__":
    main()