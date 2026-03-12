import json
import psycopg2
from psycopg2 import extras
from typing import List, Dict, Any, Tuple

# --- Database Connection Configuration ---
# NOTE: Replace with your actual credentials
def get_db_connection():
    """Establishes and returns a connection to the PostgreSQL database."""
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

def bulk_insert_vessel_data(json_file_path: str):
    """
    Loads vessel data from a JSON file and bulk inserts it into the 
    'vessel_records' table, using 'ID' as the unique key.
    """
    print(f"--- Starting upload for {json_file_path} ---")

    # 1. Load Data
    try:
        # --- FIX: Explicitly specify UTF-8 encoding for reliable JSON reading ---
        with open(json_file_path, 'r', encoding='utf-8') as f:
            vessel_data_list: List[Dict[str, Any]] = json.load(f)
    except FileNotFoundError:
        print(f"❌ Error: JSON file not found at '{json_file_path}'")
        return
    except json.JSONDecodeError:
        print(f"❌ Error: Invalid JSON format in '{json_file_path}'")
        return
    except UnicodeDecodeError as e:
        print(f"❌ Encoding Error: Failed to read file with UTF-8 encoding. Check file integrity.")
        print(f"Details: {e}")
        return

    # 2. Transform Data for executemany
    # Tuple format required for execute_batch: (id, jsonb_data_str)
    data_to_insert: List[Tuple[Any, str]] = []
    for record in vessel_data_list:
        vessel_id = record.get("ID")
        
        # We must have an ID to use as the primary key
        if vessel_id is not None:
            # Dumps the entire dictionary as a JSON string for the JSONB column
            jsonb_data_str = json.dumps(record)
            data_to_insert.append((vessel_id, jsonb_data_str))
        else:
            print(f"⚠️ Warning: Skipping record due to missing 'ID' field: {record}")

    if not data_to_insert:
        print("⚠️ Warning: No valid records found to insert. Check 'ID' field in JSON data.")
        return

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # 3. Define the INSERT query
        insert_query = """
        INSERT INTO vessel_records (id, data) 
        VALUES (%s, %s::jsonb) 
        ON CONFLICT (id) DO NOTHING
        """

        # 4. Execute the bulk insert
        extras.execute_batch(cursor, insert_query, data_to_insert, page_size=1000)

        # 5. Commit the changes
        conn.commit()
        print(f"✅ Successfully inserted {len(data_to_insert)} records into vessel_records.")

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
    bulk_insert_vessel_data('Allvessels.json')