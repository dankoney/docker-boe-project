import json
import psycopg2
from psycopg2 import extras
# Assuming get_api_connection is defined in api.db_connect
# from api.db_connect import get_api_connection 

# Replace this with your actual connection details/function
def get_db_connection():
    # --- Actual connection parameters ---
    conn = psycopg2.connect(
        dbname="postgres",
        user="postgres",
        password="dobte7-kaxgoq-xytZug",
        host="declaration-db.ct8kgqkmy6bu.eu-north-1.rds.amazonaws.com",
        port="5432"

        #DB_NAME = "Declaration_db" 
#DB_USER = "postgres"
#DB_PASS = "Danlyn@2021" 
#DB_HOST = "localhost"
#DB_PORT = "5432"
    )
    return conn

def bulk_insert_port_codes(json_file_path):
    # 1. Load Data
    try:
        with open(json_file_path, 'r') as f:
            port_data_list = json.load(f)
    except FileNotFoundError:
        print(f"❌ Error: JSON file not found at '{json_file_path}'")
        return
    except json.JSONDecodeError:
        print(f"❌ Error: Invalid JSON format in '{json_file_path}'")
        return

    # 2. Transform Data for executemany
    data_to_insert = []
    for record in port_data_list:
        port_code = record.get("PortCode")
        if port_code:
            jsonb_data_str = json.dumps(record)
            data_to_insert.append((port_code, jsonb_data_str))

    if not data_to_insert:
        print("⚠️ Warning: No valid records found to insert. Check 'PortCode' field in JSON data.")
        return

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # 3. Define the INSERT query
        insert_query = "INSERT INTO port_codes (port_code, data) VALUES (%s, %s::jsonb) ON CONFLICT (port_code) DO NOTHING"

        # 4. Execute the bulk insert
        extras.execute_batch(cursor, insert_query, data_to_insert)

        # 5. Commit the changes
        conn.commit()
        print(f"✅ Successfully inserted {len(data_to_insert)} records into port_codes.")

    except psycopg2.errors.UniqueViolation as e:
        print(f"❌ Error: Primary Key Violation (Duplicate Port Codes). You may need to use ON CONFLICT to ignore duplicates or clean your data.")
        print(e)
        if conn:
            conn.rollback()
    except (Exception, psycopg2.Error) as error:
        print(f"❌ Database Error during bulk insertion: {error}")
        if conn:
            conn.rollback()
            
    finally:
        if conn:
            conn.close()

# ----------------------------------------------------------------------
# --- EXECUTION ---
# ----------------------------------------------------------------------

if __name__ == "__main__":
    # >>> CHANGE 'ports.json' to the actual name of your file <<<
    bulk_insert_port_codes('ports.json')