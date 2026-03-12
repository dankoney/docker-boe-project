import json
import psycopg2
from datetime import datetime
import sys
import os
import glob
import shutil # <-- NEW IMPORT
from db_connect import get_loader_connection


# --- 2. Input File Directories ---
JSON_DIR_PATH = 'json_files'
PROCESSED_DIR_PATH = 'json_files_processed' # <-- NEW PROCESSED FOLDER
FILE_PATTERN = 'Declaration_Json_*.json'



def load_file_to_db(cursor, file_path):
    """Processes a single JSON file and inserts records into the database."""
    total_records = 0
    insert_count = 0
    skip_count = 0
    
    print(f"\nProcessing file: {os.path.basename(file_path)}...")

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            full_data = json.load(f)

        boe_list = full_data.get('encodingData', {}).get('response', [])
        total_records = len(boe_list)
        print(f"   Found {total_records} records.")
        
        for boe_record in boe_list:
            header = boe_record.get('boeHeader', {})
            
            # 1. Extract and Format Primary Fields
            try:
                # Date Formatting: DD/MM/YYYY to YYYY-MM-DD
                boe_date_str = header.get('boeDate')
                if not boe_date_str:
                     skip_count += 1
                     continue
                     
                boe_date_formatted = datetime.strptime(boe_date_str, '%d/%m/%Y').strftime('%Y-%m-%d')
                
                # Extract Indexed Fields
                crn_val = header.get('crn')
                boe_no_val = header.get('boeNo')
                bl_number_val = header.get('blNumber') 
                
                if not crn_val or not boe_no_val:
                    skip_count += 1
                    continue

            except (ValueError, TypeError) as e:
                skip_count += 1
                continue

            # 2. Prepare the entire BOE record for the JSONB column
            jsonb_data = json.dumps(boe_record) 
            
            # 3. SQL Insert Statement
            insert_query = """
            INSERT INTO boe_records (crn, boe_no, boe_date, bl_number, data) 
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (crn, boe_no) DO NOTHING;
            """
            
            cursor.execute(insert_query, (crn_val, boe_no_val, boe_date_formatted, bl_number_val, jsonb_data))
            insert_count += 1
            
        print(f"   Inserted {insert_count} new records. Skipped {skip_count}.")
        return insert_count

    except Exception as e:
        print(f"\n--- ERROR PROCESSING {file_path} ---")
        print(f"Error: {e}")
        return 0


def main_loader():
    """Main function to find all files, manage the transaction, and move files."""
    
    # Ensure the processed directory exists
    os.makedirs(PROCESSED_DIR_PATH, exist_ok=True)
    
    conn = get_loader_connection()
    cursor = conn.cursor()
    total_inserted = 0
    
    # 1. Find all files matching the pattern
    full_pattern = os.path.join(JSON_DIR_PATH, FILE_PATTERN)
    file_list = glob.glob(full_pattern)
    
    if not file_list:
        print(f"🛑 No files found matching '{FILE_PATTERN}' in the '{JSON_DIR_PATH}' folder.")
        conn.close()
        return

    print(f"Found {len(file_list)} files for processing.")

    # 2. Process each file
    try:
        for file_path in file_list:
            original_file_name = os.path.basename(file_path)
            
            # Load data for the current file
            inserted = load_file_to_db(cursor, file_path)
            total_inserted += inserted
            
            # Move file only if data loading was successful (inserted >= 0)
            if inserted >= 0:
                new_file_path = os.path.join(PROCESSED_DIR_PATH, original_file_name)
                shutil.move(file_path, new_file_path)
                print(f"   Moved to: {PROCESSED_DIR_PATH}")
        
        # Commit the transaction after all files are processed
        conn.commit()
        print(f"\n✅ All files processed successfully!")
        print(f"   TOTAL NEW RECORDS INSERTED ACROSS ALL FILES: {total_inserted}")
        
    except Exception as e:
        conn.rollback() 
        print(f"\n--- FATAL ERROR: Transaction rolled back. ---")
        print(f"Error: {e}")
    
    finally:
        cursor.close()
        conn.close()
        print("Database connection closed.")

if __name__ == "__main__":
    main_loader()