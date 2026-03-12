import xml.etree.ElementTree as ET
import json
import os
import shutil
import psycopg2
import psycopg2.extras 
from datetime import datetime
from typing import Dict, Any, List, Optional
from db_connect import get_loader_connection


# --- Configuration ---
XML_INPUT_DIR = "XML_files"
XML_PROCESSED_DIR = "XML_files_processed"


# --- Safe Extraction and Conversion Helpers ---

def safe_extract(element: ET.Element, xpath: str, default: Optional[Any] = '') -> Optional[Any]:
    """Extracts text from an XML element using XPath, returning a default if not found."""
    found = element.find(xpath)
    return found.text.strip() if found is not None and found.text else default

def safe_int_extract(element: ET.Element, xpath: str, default: int = 0) -> int:
    """Robustly converts extracted value to an integer, handling non-numeric strings."""
    value = safe_extract(element, xpath)
    if value is None:
        return default
    try:
        # Handles floating point numbers that are actually integers (e.g., '1.0')
        return int(float(value)) if value else default
    except (ValueError, TypeError):
        return default

def safe_float_extract(element: ET.Element, xpath: str, default: float = 0.0) -> float:
    """Robustly converts extracted value to a float."""
    value = safe_extract(element, xpath)
    if value is None:
        return default
    try:
        return float(value) if value else default
    except (ValueError, TypeError):
        return default

def convert_date(date_str: str) -> Optional[datetime.date]:
    """Converts YYYYMMDD string to a datetime.date object (PostgreSQL date type)."""
    if not date_str or not isinstance(date_str, str):
        return None
    try:
        # Date strings in the XML are typically YYYYMMDD
        return datetime.strptime(date_str[:8], '%Y%m%d').date()
    except ValueError:
        return None

def convert_timestamp(timestamp_str: str) -> Optional[datetime]:
    """Converts a timestamp string (e.g., YYYY-MM-DD HH:MM:SS.0 or YYYYMMDD) to datetime."""
    if not timestamp_str or not isinstance(timestamp_str, str):
        return None
    
    timestamp_str = timestamp_str.split('.')[0].strip() 
    try:
        if len(timestamp_str) == 8 and timestamp_str.isdigit():
            # If it's just a date, convert it to datetime at midnight
            return datetime.strptime(timestamp_str, '%Y%m%d')
        # Tries to handle the full format if present
        return datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
    except ValueError:
        return None

def parse_cargo_type(bl_element: ET.Element) -> Optional[str]:
    """Extracts the CargoType XML block and serializes it to a JSON string."""
    cargo_element = bl_element.find('./CargoType')
    if cargo_element is None:
        return None
    
    cargo_data = {}
    for child in cargo_element:
        # Uses tag name as key, and 'Y'/'N' value as string value
        cargo_data[child.tag] = child.text.strip() if child.text else None

    # Serializes Python dict to JSON string for the JSONB column
    return json.dumps(cargo_data)


def parse_manifest_xml(xml_file_path: str) -> Dict[str, Any]:
    """
    Parses the XML file and extracts structured data for DB insertion, 
    including a complete set of header fields.
    """
    try:
        tree = ET.parse(xml_file_path)
    except ET.ParseError as e:
        print(f"Error parsing XML file {xml_file_path}: {e}")
        return {'header': {}, 'bl_list': [], 'container_list': [], 'vehicle_list': []}

    root = tree.getroot()
    
    parsed_data = {
        'header': {}, 
        'bl_list': [], 
        'container_list': [], 
        'vehicle_list': []
    }

    # --- XML Block References for Cleaner Extraction ---
    doc_ref = root.find('./DocumentHeader/DocumentReference')
    doc_exchange = root.find('./DocumentHeader/DocumentExchangeDetails')
    header_details = root.find('./DocumentDetails/ManifestDocDetails/ManifestHeaderDetails')
    vessel_details = header_details.find('./VesselAircraftDetails') if header_details is not None else None
    port_details = header_details.find('./PortDetails') if header_details is not None else None
    arrival_details = header_details.find('./ArrivalDetails') if header_details is not None else None
    doc_summary = root.find('./DocumentSummary')
    
    # --- 1. Extract FULL Header Data (UPDATED to ensure all fields are correctly targeted) ---
    header_data = {}
    
    # Document Reference
    header_data['crn'] = safe_extract(doc_ref, './CommonRefNumber')
    header_data['document_type'] = safe_extract(doc_ref, './DocumentType')
    header_data['document_name'] = safe_extract(doc_ref, './DocumentName')
    header_data['document_number'] = safe_extract(doc_ref, './DocumentNumber')
    header_data['message_type'] = safe_extract(doc_ref, './MessageType') # <-- Added
    header_data['sender_id'] = safe_extract(doc_ref, './SenderID')       # <-- Added
    
    # Document Exchange Details
    header_data['receiving_party'] = safe_extract(doc_exchange, './ReceivingPartyDetails/ReceivingParty') # <-- Added
    
    # Extract notify parties list and store as JSON string
    notify_parties_elements = doc_exchange.findall('./NotifyPartyDetails/NotifyParty') if doc_exchange is not None else []
    notify_parties_list = [n.text.strip() for n in notify_parties_elements if n.text and n.text.strip()]
    header_data['notify_parties'] = json.dumps(notify_parties_list) # <-- Added

    # Vessel Details
    header_data['rotation_no'] = safe_extract(vessel_details, './RotationNo')
    header_data['rotation_no_creation_date'] = convert_date(safe_extract(vessel_details, './RotationNoCreationDate')) # <-- Added
    header_data['vessel_name'] = safe_extract(vessel_details, './VesselName')
    header_data['voyage_no'] = safe_extract(vessel_details, './VoyageNo')
    header_data['carrier_code'] = safe_extract(vessel_details, './CarrierCode')
    header_data['carrier_name'] = safe_extract(vessel_details, './carrier') # Corrected tag name from XML
    header_data['vessel_nationality'] = safe_extract(vessel_details, './VesselNationality') # <-- Added
    header_data['coload_yn'] = safe_extract(vessel_details, './ColoadYn') # <-- Added

    # Port Details
    header_data['inbound_outbound'] = safe_extract(port_details, './InboundOutbound') # <-- Added
    header_data['transport_mode'] = safe_extract(port_details, './TransportMode')     # <-- Added
    header_data['port_of_discharge'] = safe_extract(port_details, './PortOfDischarge')
    header_data['port_of_loading'] = safe_extract(port_details, './PortOfLoading')
    header_data['next_port_of_call'] = safe_extract(port_details, './NextPortOfCall') # <-- Added
    header_data['final_destination'] = safe_extract(port_details, './FinalDestination') # <-- Added
    header_data['shipping_agent_code'] = safe_extract(port_details, './ShippingAgentCode') # <-- Added
    header_data['agent_name'] = safe_extract(port_details, './AgentName')
    header_data['customs_office_code'] = safe_extract(port_details, './CustomsOfficeCode') # <-- Added

    # Arrival Details
    header_data['eta'] = convert_date(safe_extract(arrival_details, './ETA'))
    header_data['etd'] = convert_date(safe_extract(arrival_details, './ETD'))

    # Document Summary (Issued Date)
    header_data['issued_date'] = convert_date(safe_extract(doc_summary, './IssuedDateTime')) # <-- Added
    
    # Placeholder for DB-managed field
    header_data['last_amended_at'] = None 
    
    parsed_data['header'] = header_data

    # --- 2. Extract Bill of Lading (BL), Container, and Vehicle Details (Original Logic) ---
    BL_LIST_PATH = "./DocumentDetails/ManifestDocDetails/ManifestDetails/BillOfLadingDetails/BillOfLading"
    for bl_element in root.findall(BL_LIST_PATH):
        
        bl_number = safe_extract(bl_element, './BLNumber')
        bl_version_no = safe_int_extract(bl_element, './BLVersionNo')

        if not bl_number: continue
        
        # A. BL Main Details
        bl_data = {
            'crn': header_data['crn'],
            'bl_number': bl_number,
            'bl_version_no': bl_version_no,
            'master_bl_number': safe_extract(bl_element, './MasterBLNumber'),
            'consignee_name': safe_extract(bl_element, './ConsigneeName'),
            'consignee_address': safe_extract(bl_element, './ConsigneeAddress'),
            'shipper_name': safe_extract(bl_element, './ShipperName'),
            'goods_description': safe_extract(bl_element, './GoodsDescription'),
            'gross_weight': safe_float_extract(bl_element, './GrossWeight'),
            'volume': safe_float_extract(bl_element, './Volume'),
            'no_of_packages': safe_int_extract(bl_element, './NoOfPackages'),
            'unit': safe_extract(bl_element, './Unit'),
            'no_of_containers': safe_int_extract(bl_element, './NoOfContainers'),
            'no_of_vehicles': safe_int_extract(bl_element, './NoOfVehicles'),
            'imdg_codes': safe_extract(bl_element, './IMDGCodes'),
            'bl_type': safe_extract(bl_element, './BLType'),
            'port_of_loading': safe_extract(bl_element, './PortOfLoading'),
            'port_of_discharge': safe_extract(bl_element, './PortOfDischarge'),
            'place_of_receipt': safe_extract(bl_element, './PlaceOfReceipt'),
            'place_of_delivery': safe_extract(bl_element, './PlaceOfDelivery'),
            'cargo_type_json': parse_cargo_type(bl_element), 
            'freight_amount': safe_float_extract(bl_element, './FreightAmount'), 
            'submitted_date': convert_date(safe_extract(bl_element, './SubmittedDate')), 
        }
        parsed_data['bl_list'].append(bl_data)

        # B. Container Details
        for container in bl_element.findall('./Containers/ContainersDetails'):
            container_data = {
                'bl_number': bl_number,
                'bl_version_no': bl_version_no,
                'container_no': safe_extract(container, './ContainerNo'),
                'seal_number': safe_extract(container, './SealNumber'),
                'container_type': safe_extract(container, './ContainerType'),
                'container_size': safe_int_extract(container, './ContainerSize'), 
                'freight_indicator': safe_extract(container, './FreightIndicator'),
                'load_status': safe_extract(container, './LoadStatus'),
                'gross_weight': safe_float_extract(container, './GrossWeight'),
                'number_of_packages': safe_int_extract(container, './NumberOfPackages'),
                'unit': safe_extract(container, './Unit'),
                'iso_code': safe_extract(container, './ISOCode'),
            }
            parsed_data['container_list'].append(container_data)

        # C. Vehicle Details 
        for vehicle in bl_element.findall('./Vehicles/VehicleDetails'):
            vehicle_data = {
                'bl_number': bl_number,
                'bl_version_no': bl_version_no,
                'chassis_no': safe_extract(vehicle, './ChassisNo'),
                'model': safe_extract(vehicle, './Model'),
                'make': safe_extract(vehicle, './Make'),
            }
            parsed_data['vehicle_list'].append(vehicle_data)

    return parsed_data


# --- SQL Template Definitions (UNCHANGED from last update, as it was already complete) ---

HEADER_UPSERT_SQL = """
INSERT INTO manifest_header (
    crn, document_type, document_name, document_number, message_type, sender_id, 
    receiving_party, notify_parties, rotation_no, rotation_no_creation_date, vessel_name, 
    voyage_no, carrier_code, carrier_name, vessel_nationality, coload_yn, 
    inbound_outbound, transport_mode, port_of_discharge, port_of_loading, 
    next_port_of_call, final_destination, shipping_agent_code, agent_name, 
    customs_office_code, eta, etd, issued_date, last_amended_at
)
VALUES (
    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 
    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP
)
ON CONFLICT (crn) DO UPDATE
SET 
    document_type = EXCLUDED.document_type,
    document_name = EXCLUDED.document_name,
    document_number = COALESCE(EXCLUDED.document_number, manifest_header.document_number),
    message_type = COALESCE(EXCLUDED.message_type, manifest_header.message_type),
    sender_id = COALESCE(EXCLUDED.sender_id, manifest_header.sender_id),
    receiving_party = COALESCE(EXCLUDED.receiving_party, manifest_header.receiving_party),
    notify_parties = COALESCE(EXCLUDED.notify_parties, manifest_header.notify_parties),
    rotation_no = COALESCE(EXCLUDED.rotation_no, manifest_header.rotation_no),
    rotation_no_creation_date = COALESCE(EXCLUDED.rotation_no_creation_date, manifest_header.rotation_no_creation_date),
    vessel_name = COALESCE(EXCLUDED.vessel_name, manifest_header.vessel_name),
    voyage_no = COALESCE(EXCLUDED.voyage_no, manifest_header.voyage_no),
    carrier_code = COALESCE(EXCLUDED.carrier_code, manifest_header.carrier_code),
    carrier_name = COALESCE(EXCLUDED.carrier_name, manifest_header.carrier_name),
    vessel_nationality = COALESCE(EXCLUDED.vessel_nationality, manifest_header.vessel_nationality),
    coload_yn = COALESCE(EXCLUDED.coload_yn, manifest_header.coload_yn),
    inbound_outbound = COALESCE(EXCLUDED.inbound_outbound, manifest_header.inbound_outbound),
    transport_mode = COALESCE(EXCLUDED.transport_mode, manifest_header.transport_mode),
    port_of_discharge = COALESCE(EXCLUDED.port_of_discharge, manifest_header.port_of_discharge),
    port_of_loading = COALESCE(EXCLUDED.port_of_loading, manifest_header.port_of_loading),
    next_port_of_call = COALESCE(EXCLUDED.next_port_of_call, manifest_header.next_port_of_call),
    final_destination = COALESCE(EXCLUDED.final_destination, manifest_header.final_destination),
    shipping_agent_code = COALESCE(EXCLUDED.shipping_agent_code, manifest_header.shipping_agent_code),
    agent_name = COALESCE(EXCLUDED.agent_name, manifest_header.agent_name),
    customs_office_code = COALESCE(EXCLUDED.customs_office_code, manifest_header.customs_office_code),
    eta = COALESCE(EXCLUDED.eta, manifest_header.eta),
    etd = COALESCE(EXCLUDED.etd, manifest_header.etd),
    issued_date = COALESCE(EXCLUDED.issued_date, manifest_header.issued_date),
    last_amended_at = CURRENT_TIMESTAMP;
"""
UPDATE_PREV_BL_VERSION_SQL = """
UPDATE manifest_bl_details
SET latest_bl = FALSE
WHERE bl_number = %s AND crn = %s AND latest_bl = TRUE;
"""
INSERT_NEW_BL_SQL = """
INSERT INTO manifest_bl_details (
    crn, bl_number, bl_version_no, master_bl_number, consignee_name, consignee_address, shipper_name,
    goods_description, gross_weight, volume, no_of_packages, unit, no_of_containers, no_of_vehicles,
    imdg_codes, bl_type, port_of_loading, port_of_discharge, place_of_receipt, place_of_delivery,
    cargo_type_json, freight_amount, submitted_date, latest_bl
)
VALUES (
    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE
) ON CONFLICT (bl_number, bl_version_no) DO NOTHING;
"""
DELETE_CONTAINERS_SQL = """
DELETE FROM manifest_container_details 
WHERE bl_number = %s AND bl_version_no = %s;
"""

DELETE_VEHICLES_SQL = """
DELETE FROM manifest_vehicle_details 
WHERE bl_number = %s AND bl_version_no = %s;
"""

INSERT_CONTAINER_SQL = """
INSERT INTO manifest_container_details (
    bl_number, bl_version_no, container_no, seal_number, container_type, container_size, 
    freight_indicator, load_status, gross_weight, number_of_packages, unit, iso_code
) VALUES (
    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
);
"""
INSERT_VEHICLE_SQL = """
INSERT INTO manifest_vehicle_details (
    bl_number, bl_version_no, chassis_no, model, make
) VALUES (
    %s, %s, %s, %s, %s
);
"""
CHECK_BL_EXISTS_SQL = """
SELECT EXISTS(
    SELECT 1 FROM manifest_bl_details 
    WHERE bl_number = %s AND crn = %s
);
"""


# --- Ingestion Function ---

def ingest_manifest_data(file_path: str) -> bool:
    """Attempts to ingest a single XML file into the database. Returns True on success."""
    
    parsed_data = None 
    conn = get_loader_connection()
    if not conn:
        return False

    try:
        parsed_data = parse_manifest_xml(file_path)
        
        header = parsed_data['header']
        bl_list = parsed_data['bl_list']
        container_list = parsed_data['container_list']
        vehicle_list = parsed_data['vehicle_list']

        if not header or not header.get('crn'):
            print(f"[{os.path.basename(file_path)}] Skipping: CRN not found or XML content incomplete.")
            return False

        doc_type = header['document_type']
        cursor = conn.cursor()
        
        # --- PHASE 1: Header Ingestion ---
        # NOTE: The order of parameters MUST match the INSERT column order in HEADER_UPSERT_SQL
        header_params = (
            header.get('crn'), header.get('document_type'), header.get('document_name'), header.get('document_number'), 
            header.get('message_type'), header.get('sender_id'), header.get('receiving_party'), header.get('notify_parties'), 
            header.get('rotation_no'), header.get('rotation_no_creation_date'), header.get('vessel_name'), 
            header.get('voyage_no'), header.get('carrier_code'), header.get('carrier_name'), header.get('vessel_nationality'), 
            header.get('coload_yn'), header.get('inbound_outbound'), header.get('transport_mode'), 
            header.get('port_of_discharge'), header.get('port_of_loading'), header.get('next_port_of_call'), 
            header.get('final_destination'), header.get('shipping_agent_code'), header.get('agent_name'), 
            header.get('customs_office_code'), header.get('eta'), header.get('etd'), header.get('issued_date')
        )
        
        # Handling for amendment/addendum documents where key fields might be missing initially
        if doc_type in ['AMNDOC', 'ADLDOC'] and not header.get('vessel_name'): 
            # We insert minimal fields to reserve the CRN if full details aren't present
            # Creating a minimal parameter tuple matching the 28 columns expected by HEADER_UPSERT_SQL
            pending_params = (
                header.get('crn'), doc_type, None, None, None, None, None, None, 
                header.get('rotation_no'), None, None, None, None, None, None, None, 
                None, None, None, None, None, None, None, None, None, None, None, None
            )
            cursor.execute(HEADER_UPSERT_SQL, pending_params)
        
        # Execute the main UPSERT 
        cursor.execute(HEADER_UPSERT_SQL, header_params)

        # --- PHASE 2: BL Detail Ingestion (Versioning) ---
        bls_processed_keys = [] 
        
        for bl in bl_list:
            bl_params = (
                bl['crn'], bl['bl_number'], bl['bl_version_no'], bl['master_bl_number'], 
                bl['consignee_name'], bl['consignee_address'], bl['shipper_name'], bl['goods_description'], 
                bl['gross_weight'], bl['volume'], bl['no_of_packages'], bl['unit'], 
                bl['no_of_containers'], bl['no_of_vehicles'], bl['imdg_codes'], bl['bl_type'], 
                bl['port_of_loading'], bl['port_of_discharge'], bl['place_of_receipt'], bl['place_of_delivery'],
                bl['cargo_type_json'], bl['freight_amount'], bl['submitted_date']
            )
            
            bl_inserted = False
            
            # HMNDOC is only inserted if the BL/CRN combo doesn't exist (i.e., first receipt)
            if doc_type == 'HMNDOC':
                cursor.execute(CHECK_BL_EXISTS_SQL, (bl['bl_number'], header['crn']))
                if not cursor.fetchone()[0]:
                    cursor.execute(INSERT_NEW_BL_SQL, bl_params)
                    bl_inserted = True
                    
            # AMNDOC/ADLDOC always updates the latest_bl flag on the old record and inserts the new version
            elif doc_type in ['AMNDOC', 'ADLDOC']:
                cursor.execute(UPDATE_PREV_BL_VERSION_SQL, (bl['bl_number'], header['crn']))
                cursor.execute(INSERT_NEW_BL_SQL, bl_params)
                bl_inserted = True

            if bl_inserted:
                bls_processed_keys.append((bl['bl_number'], bl['bl_version_no']))

        # --- PHASE 3: DELETE Existing Child Data for the BL Versions Processed (Fix for Duplication) ---
        for bl_number, bl_version_no in bls_processed_keys:
            cursor.execute(DELETE_CONTAINERS_SQL, (bl_number, bl_version_no))
            cursor.execute(DELETE_VEHICLES_SQL, (bl_number, bl_version_no))
        
        # --- PHASE 4: Container Insertion ---
        if container_list:
            containers_to_insert = [
                c for c in container_list 
                if (c['bl_number'], c['bl_version_no']) in bls_processed_keys
            ]
            
            container_params = [
                (c['bl_number'], c['bl_version_no'], c['container_no'], c['seal_number'], c['container_type'], 
                 c['container_size'], c['freight_indicator'], c['load_status'], c['gross_weight'], 
                 c['number_of_packages'], c['unit'], c['iso_code'])
                for c in containers_to_insert
            ]
            if container_params:
                psycopg2.extras.execute_batch(cursor, INSERT_CONTAINER_SQL, container_params)

        # --- PHASE 5: Vehicle Insertion ---
        if vehicle_list:
            vehicles_to_insert = [
                v for v in vehicle_list 
                if (v['bl_number'], v['bl_version_no']) in bls_processed_keys
            ]

            vehicle_params = [
                (v['bl_number'], v['bl_version_no'], v['chassis_no'], v['model'], v['make'])
                for v in vehicles_to_insert
            ]
            if vehicle_params:
                psycopg2.extras.execute_batch(cursor, INSERT_VEHICLE_SQL, vehicle_params)

        conn.commit()
        print(f"[{os.path.basename(file_path)}] SUCCESS: {doc_type} (CRN: {header['crn']}) ingested {len(bl_list)} BLs, {len(container_list)} Containers, {len(vehicle_list)} Vehicles.")
        return True

    except psycopg2.Error as e:
        conn.rollback()
        print(f"[{os.path.basename(file_path)}] DB ERROR: Failed ingestion. {e}")
        return False
        
    except Exception as e:
        conn.rollback() 
        print(f"[{os.path.basename(file_path)}] GENERAL ERROR (Parsing/Logic): Failed ingestion. {e}")
        return False
        
    finally:
        if conn:
            conn.close()

# ----------------------------------------------------
## Main Execution Block for File Processing
# ----------------------------------------------------

def process_xml_files():
    """Main function to iterate, ingest, and move XML files."""
    
    os.makedirs(XML_PROCESSED_DIR, exist_ok=True)
    
    if not os.path.isdir(XML_INPUT_DIR):
        print(f"Error: Input directory '{XML_INPUT_DIR}' not found. Creating it.")
        os.makedirs(XML_INPUT_DIR, exist_ok=True)
        return

    print(f"--- Starting Manifest XML Ingestion from '{XML_INPUT_DIR}' ---")
    
    files_to_process = [
        f for f in os.listdir(XML_INPUT_DIR) 
        if f.endswith('.xml') or f.endswith('.XML')
    ]

    if not files_to_process:
        print("No XML files found to process.")
        return

    processed_count = 0
    error_count = 0
    
    # Process HMNDOC first to ensure base records exist before amendments (AMNDOC/ADLDOC)
    files_to_process.sort(key=lambda f: 'HMNDOC' not in f.upper()) 

    for filename in files_to_process:
        input_path = os.path.join(XML_INPUT_DIR, filename)
        
        # --- Check if the file is still there before processing ---
        if not os.path.exists(input_path):
            continue 
            
        if ingest_manifest_data(input_path):
            processed_count += 1
            processed_path = os.path.join(XML_PROCESSED_DIR, filename)
            try:
                shutil.move(input_path, processed_path)
            except Exception as e:
                print(f"CRITICAL: Failed to move file {filename} to processed folder. {e}")
        else:
            error_count += 1
            
    # Summary
    print("\n--- Manifest Ingestion Summary ---")
    print(f"Total files found: {len(files_to_process)}")
    print(f"Successfully processed and moved: **{processed_count}**")
    print(f"Failed (remain in input folder): **{error_count}**")

# --- Execution ---
if __name__ == '__main__':
    # NOTE: You will need to configure DB_CONFIG and place a dummy XML file in the XML_files directory
    # to test this main execution block.
    process_xml_files()