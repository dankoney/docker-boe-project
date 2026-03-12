import json
import os
import psycopg2.extras
import psycopg2
from fastapi import FastAPI, HTTPException, Query
from typing import Optional, List, Dict, Any, Tuple
from datetime import date, datetime

# Load .env from project root so SMTP_*, DB_*, etc. are set when running locally
try:
    from dotenv import load_dotenv
    _api_dir = os.path.dirname(os.path.abspath(__file__))
    for _path in [os.getcwd(), _api_dir, os.path.dirname(_api_dir)]:
        _env = os.path.join(_path, ".env")
        if os.path.isfile(_env):
            load_dotenv(_env)
            break
except ImportError:
    pass

from db_connect import get_api_connection
from auth import router as auth_router

# Initialize FastAPI App 
app = FastAPI(
    title="BOE Declaration Search API (Multi-Filter Optimized)",
    description="API for fast lookup of customs declaration records with PostgreSQL aggregation, supporting multiple filters."
)
app.include_router(auth_router)

# --- JSON Key Mapping & Helper Function ---
JSON_HEADER_KEY_MAP = {
    'importer_tin': 'importerTin',
    'importer_name_keywords': 'importerName',
    'vessel_name': 'vesselName',
    'place_of_landing': 'placeOfLanding',
    'port_of_loading': 'portOfLoading'
}

def execute_top_card_query(sql_template: str, cursor: Any, params: List[Any], where_clause_str: str, card_key: str, metric_key: str, grouping_field_key: str, top_cards: Dict[str, Any]):
    """
    Executes a single top card query, extracts the two resulting fields 
    (grouping field and aggregate value), and updates the top_cards dictionary.
    """
    # Safety check: replace empty where_clause_str with 'TRUE' to prevent SQL syntax errors
    effective_where_clause = where_clause_str if where_clause_str else 'TRUE'
    sql = sql_template.format(where_clause=effective_where_clause)
    
    try:
        # Pass parameters as a tuple
        cursor.execute(sql, tuple(params))
        result = cursor.fetchone()
    except Exception as e:
        # Using standard print for logging errors
        print(f"Error executing top card SQL for {card_key}: {e}")
        result = None

    top_cards[card_key] = {}
    
    if result and len(result) >= 2:
        # result[0] is the grouping value (Importer Name or HS Code)
        # result[1] is the total metric value
        aggregate_value = float(result[1]) if result[1] is not None else 0.0
        
        # Ensure result[0] is not None before assigning
        grouping_value = result[0] if result[0] is not None else "N/A"
        
        top_cards[card_key] = {
            grouping_field_key: grouping_value,
            metric_key: aggregate_value
        }

# --- AGGREGATION SQL CONSTANTS FOR REPORTING CARDS ---

# Top Importer by Net Weight (Groups only by Importer Name)
TOP_IMPORTER_NET_WEIGHT_SQL = """
    SELECT
        T.data -> 'boeHeader' ->> 'importerName' AS importer_name,
        COALESCE(SUM(
            (SELECT SUM((item ->> 'netWeight')::DECIMAL)
            FROM jsonb_array_elements(T.data -> 'boeItem') AS item)
        ), 0.0) AS total_net_weight
    FROM boe_records T
    WHERE {where_clause}
    GROUP BY 1
    ORDER BY total_net_weight DESC
    LIMIT 1;
"""

# Top Importer by Gross Weight (Groups only by Importer Name)
TOP_IMPORTER_GROSS_WEIGHT_SQL = """
    SELECT
        T.data -> 'boeHeader' ->> 'importerName' AS importer_name,
        COALESCE(SUM(
            (SELECT SUM((item ->> 'grossWeight')::DECIMAL)
            FROM jsonb_array_elements(T.data -> 'boeItem') AS item)
        ), 0.0) AS total_gross_weight
    FROM boe_records T
    WHERE {where_clause}
    GROUP BY 1
    ORDER BY total_gross_weight DESC
    LIMIT 1;
"""

# Top Importer by Value (Groups only by Importer Name, Value in GHS)
TOP_IMPORTER_VALUE_SQL = """
    SELECT
        T.data -> 'boeHeader' ->> 'importerName' AS importer_name,
        COALESCE(SUM(
            (SELECT SUM(
                (item ->> 'fobAmount')::NUMERIC *
                (T.data -> 'boeHeader' ->> 'fobExchangeRate')::NUMERIC
            )
            FROM jsonb_array_elements(T.data -> 'boeItem') AS item)
        ), 0.0) AS total_fob_value_ghs
    FROM boe_records T
    WHERE {where_clause}
    GROUP BY 1
    ORDER BY total_fob_value_ghs DESC
    LIMIT 1;
"""

# Top HS Code by Net Weight (Groups only by HS Code)
TOP_HSCODE_NET_WEIGHT_SQL = """
    SELECT
        item ->> 'hsCode' AS hscode,
        COALESCE(SUM((item ->> 'netWeight')::NUMERIC), 0.0) AS total_net_weight
    FROM boe_records T,
    jsonb_array_elements(T.data -> 'boeItem') AS item
    WHERE {where_clause}
    GROUP BY 1
    ORDER BY total_net_weight DESC
    LIMIT 1;
"""

# Top HS Code by Gross Weight (Groups only by HS Code)
TOP_HSCODE_GROSS_WEIGHT_SQL = """
    SELECT
        item ->> 'hsCode' AS hscode,
        COALESCE(SUM((item ->> 'grossWeight')::NUMERIC), 0.0) AS total_gross_weight
    FROM boe_records T,
    jsonb_array_elements(T.data -> 'boeItem') AS item
    WHERE {where_clause}
    GROUP BY 1
    ORDER BY total_gross_weight DESC
    LIMIT 1;
"""

# Top HS Code by Value (Groups only by HS Code, Value in GHS)
TOP_HSCODE_VALUE_SQL = """
    SELECT
        item ->> 'hsCode' AS hscode,
        COALESCE(SUM(
            (item ->> 'fobAmount')::NUMERIC *
            (T.data -> 'boeHeader' ->> 'fobExchangeRate')::NUMERIC
        ), 0.0) AS total_fob_value_ghs
    FROM boe_records T,
    jsonb_array_elements(T.data -> 'boeItem') AS item
    WHERE {where_clause}
    GROUP BY 1
    ORDER BY total_fob_value_ghs DESC
    LIMIT 1;
"""


# ----------------------------------------------
# --- SUGGESTION ENDPOINTS ---
# ----------------------------------------------

@app.get("/hscodes/suggestions", response_model=List[Dict[str, str]])
async def get_hscode_suggestions(prefix: str = Query(..., min_length=4)):
    """Provides auto-complete suggestions for HS Codes based on a prefix."""
    conn = get_api_connection()
    if not conn:
        raise HTTPException(status_code=503, detail="Database service unavailable.")

    try:
        cursor = conn.cursor()
        sql = """
            SELECT DISTINCT
                (boe_item ->> 'hsCode') AS hscode
            FROM boe_records,
            jsonb_array_elements(data -> 'boeItem') AS boe_item
            WHERE (boe_item ->> 'hsCode') LIKE %s
            LIMIT 20;
        """
        cursor.execute(sql, (f"{prefix}%",))
        raw_results = cursor.fetchall()

        suggestions = []
        for row in raw_results:
            suggestions.append({
                "hscode": row[0],
                "description": "No description available" # Placeholder, actual description would need a lookup table
            })

        return suggestions

    except Exception as e:
        print(f"Error fetching HS Code suggestions: {e}")
        raise HTTPException(status_code=500, detail="Internal server error during suggestion retrieval.")
    finally:
        if 'conn' in locals() and conn:
            conn.close()

@app.get("/suggestions/vessel", response_model=List[Dict[str, str]])
async def get_vessel_suggestions(keyword: str = Query(..., min_length=3)):
    """Provides auto-complete suggestions for Vessel Names."""
    conn = get_api_connection()
    if not conn:
        raise HTTPException(status_code=503, detail="Database service unavailable.")
    try:
        cursor = conn.cursor()
        sql = """
            SELECT DISTINCT
                T.data -> 'boeHeader' ->> 'vesselName' AS name,
                T.data -> 'boeHeader' ->> 'vesselNationality' AS vesselNationality
            FROM boe_records T
            WHERE T.data -> 'boeHeader' ->> 'vesselName' ILIKE %s
            AND T.data -> 'boeHeader' ->> 'vesselName' IS NOT NULL
            LIMIT 20;
        """
        cursor.execute(sql, (f"{keyword}%",))
        raw_results = cursor.fetchall()

        suggestions = [
            {
                "name": row[0],
                "vesselNationality": row[1] if row[1] is not None else 'N/A'
            }
            for row in raw_results if row[0]
        ]
        return suggestions

    except Exception as e:
        print(f"Error fetching Vessel suggestions: {e}")
        raise HTTPException(status_code=500, detail="Internal server error during suggestion retrieval.")
    finally:
        if 'conn' in locals() and conn:
            conn.close()

@app.get("/suggestions/importer", response_model=List[Dict[str, str]])
async def get_importer_suggestions(keyword: str = Query(..., min_length=3)):
    """Provides auto-complete suggestions for Importer Names."""
    conn = get_api_connection()
    if not conn:
        raise HTTPException(status_code=503, detail="Database service unavailable.")
    try:
        cursor = conn.cursor()
        sql = """
            SELECT DISTINCT
                T.data -> 'boeHeader' ->> 'importerName' AS name,
                T.data -> 'boeHeader' ->> 'importerTin' AS importerTin
            FROM boe_records T
            WHERE T.data -> 'boeHeader' ->> 'importerName' ILIKE %s
            AND T.data -> 'boeHeader' ->> 'importerName' IS NOT NULL
            LIMIT 20;
        """
        cursor.execute(sql, (f"%{keyword}%",))
        raw_results = cursor.fetchall()

        suggestions = [
            {
                "name": row[0],
                "importerTin": row[1] if row[1] is not None else 'N/A'
            }
            for row in raw_results if row[0]
        ]
        return suggestions

    except Exception as e:
        print(f"Error fetching Importer suggestions: {e}")
        raise HTTPException(status_code=500, detail="Internal server error during suggestion retrieval.")
    finally:
        if 'conn' in locals() and conn:
            conn.close()


# ----------------------------------------------
# --- MAIN ENDPOINT: MULTI-SEARCH REPORTS ---
# ----------------------------------------------

@app.get("/reports/cargo/", response_model=Dict[str, Any])
async def get_multi_filter_report(
    start_date: date = Query(..., description="BOE Start Date (Inclusive)"),
    end_date: date = Query(..., description="BOE End Date (Inclusive)"),
    country_of_origin: Optional[str] = Query(None, description="Search by Item Origin Country"),
    hscode: Optional[List[str]] = Query(None, description="Search by HS Code (List of 4, 6, or 8-digit prefixes)"),
    boe_number: Optional[str] = Query(None, description="Search by BOE Number (Exact match)"),
    importer_tin: Optional[str] = Query(None, description="Search by Importer TIN"),
    bl_number: Optional[str] = Query(None, description="Search by BL Number (Exact match)"),
    vessel_name: Optional[List[str]] = Query(None, description="Search by Vessel Name (List of keywords/names)"),
    importer_name_keywords: Optional[List[str]] = Query(None, description="Search by Importer Name (List of keywords/names)"),
    goods_description_keywords: Optional[List[str]] = Query(None, description="Search by Goods Description (List of keywords)"),
    limit: int = Query(100, description="Maximum number of records to return")
):
    """
    Retrieves summary aggregations and detailed records for customs declarations 
    based on a wide range of filters.
    """
    conn = get_api_connection()
    if not conn:
        raise HTTPException(status_code=503, detail="Database service unavailable.")

    try:
        cursor = conn.cursor()

        # --- 1. Dynamic WHERE Clause Builder ---
        where_clauses = ["T.boe_date BETWEEN %s AND %s"]
        params_base = [start_date, end_date]

        filter_values = {
            'country_of_origin': country_of_origin, 'hscode': hscode, 'boe_number': boe_number,
            'importer_tin': importer_tin, 'bl_number': bl_number,
            'vessel_name': vessel_name, 'importer_name_keywords': importer_name_keywords,
            'goods_description_keywords': goods_description_keywords,
        }

        for api_param, value in filter_values.items():
            if not value:
                continue
            
            # Exact Match on indexed columns
            if api_param in ['boe_number', 'bl_number']:
                db_column = 'boe_no' if api_param == 'boe_number' else 'bl_number'
                where_clauses.append(f"T.{db_column} = %s")
                params_base.append(value)
            
            # JSONB Contains for Importer TIN
            elif api_param == 'importer_tin':
                json_key = JSON_HEADER_KEY_MAP[api_param]
                # Using @> operator for efficient JSONB search
                where_clauses.append(f"T.data @> %s")
                params_base.append(json.dumps({"boeHeader": {json_key: value}}))
            
            # HS Code (List, prefix match)
            elif api_param == 'hscode' and isinstance(value, list) and value:
                hscode_or_clauses = []
                for code in value:
                    code_str = str(code).strip()
                    prefix = f"{code_str[:min(len(code_str), 8)]}%"
                    if len(code_str) >= 4:
                        inner_item_check = """
                            EXISTS (
                                SELECT 1 FROM jsonb_array_elements(T.data -> 'boeItem') AS item
                                WHERE item ->> 'hsCode' LIKE %s
                            )
                        """
                        hscode_or_clauses.append(inner_item_check)
                        params_base.append(prefix)
                if hscode_or_clauses:
                    full_hscode_clause = " OR ".join(hscode_or_clauses)
                    where_clauses.append(f"({full_hscode_clause})")
            
            # Country of Origin (JSONB Contains on item array)
            elif api_param == 'country_of_origin':
                # This checks if ANY item has the matching country
                where_clauses.append(f"T.data -> 'boeItem' @> %s")
                params_base.append(json.dumps([{"itemOriginCountry": value}]))
            
            # Text Keywords (Vessel Name, Importer Name, Goods Description)
            elif api_param in ['vessel_name', 'importer_name_keywords', 'goods_description_keywords'] and isinstance(value, list) and value:
                jsonb_key_map = {
                    'vessel_name': "vesselName",
                    'importer_name_keywords': "importerName",
                    'goods_description_keywords': "goodsDescription",
                }
                jsonb_field_name = jsonb_key_map.get(api_param)
                keyword_or_clauses = []
                for keyword in value:
                    if jsonb_field_name in ["vesselName", "importerName"]:
                        db_field = f"T.data -> 'boeHeader' ->> '{jsonb_field_name}'"
                        keyword_or_clauses.append(f"{db_field} ILIKE %s")
                        params_base.append(f"%{keyword}%")
                    elif jsonb_field_name == "goodsDescription":
                        # Check goodsDescription within the boeItem array
                        inner_item_check = """
                            EXISTS (
                                SELECT 1 FROM jsonb_array_elements(T.data -> 'boeItem') AS item
                                WHERE item ->> 'goodsDescription' ILIKE %s
                            )
                        """
                        keyword_or_clauses.append(inner_item_check)
                        params_base.append(f"%{keyword}%")
                if keyword_or_clauses:
                    full_keyword_clause = " OR ".join(keyword_or_clauses)
                    where_clauses.append(f"({full_keyword_clause})")

        where_clause_str = " AND ".join(where_clauses)

        # --- 2. Query 1: Get Summary Totals (Grand Totals) ---
        SUMMARY_AGGREGATION_CLAUSE = """
            SELECT
                COUNT(T.crn) AS total_records,
                COALESCE(SUM(
                    (SELECT SUM((item ->> 'netWeight')::DECIMAL)
                    FROM jsonb_array_elements(T.data -> 'boeItem') AS item)
                ), 0.0) AS grand_total_net_weight,
                COALESCE(SUM(
                    (SELECT SUM((item ->> 'grossWeight')::DECIMAL)
                    FROM jsonb_array_elements(T.data -> 'boeItem') AS item)
                ), 0.0) AS grand_total_gross_weight
            FROM boe_records T
        """
        sql_summary = f"{SUMMARY_AGGREGATION_CLAUSE} WHERE {where_clause_str};"
        cursor.execute(sql_summary, tuple(params_base))
        summary_result = cursor.fetchone()

        summary = {
            "total_records": summary_result[0] if summary_result else 0,
            "grand_total_net_weight": float(summary_result[1]) if summary_result and summary_result[1] is not None else 0.0,
            "grand_total_gross_weight": float(summary_result[2]) if summary_result and summary_result[2] is not None else 0.0,
        }

        # --- 2.5. Get Top Cards (Aggregated Metrics) ---
        top_cards = {}
        
        if summary["total_records"] > 0:
            
            # Importer Only Cards
            execute_top_card_query(TOP_IMPORTER_NET_WEIGHT_SQL, cursor, params_base,
                                   where_clause_str, "top_importer_net_weight", "total_net_weight", "importer_name", top_cards)
            execute_top_card_query(TOP_IMPORTER_GROSS_WEIGHT_SQL, cursor, params_base,
                                   where_clause_str, "top_importer_gross_weight", "total_gross_weight", "importer_name", top_cards)
            execute_top_card_query(TOP_IMPORTER_VALUE_SQL, cursor, params_base,
                                   where_clause_str, "top_importer_fob_value", "total_fob_value_ghs", "importer_name", top_cards)
                                           
            # HS Code Only Cards
            execute_top_card_query(TOP_HSCODE_NET_WEIGHT_SQL, cursor, params_base,
                                   where_clause_str, "top_hscode_net_weight", "total_net_weight", "hscode", top_cards)
            execute_top_card_query(TOP_HSCODE_GROSS_WEIGHT_SQL, cursor, params_base,
                                   where_clause_str, "top_hscode_gross_weight", "total_gross_weight", "hscode", top_cards)
            execute_top_card_query(TOP_HSCODE_VALUE_SQL, cursor, params_base,
                                   where_clause_str, "top_hscode_fob_value", "total_fob_value_ghs", "hscode", top_cards)


        # Integrate top_cards into the summary
        summary["top_cards"] = top_cards 
        
        if summary["total_records"] == 0:
            return {"summary": summary, "records": []}

        # --- 3. Query 2: Get Detailed Records ---
        AGGREGATION_CLAUSE = """
            SELECT
                T.data,
                T.boe_no,
                T.boe_date,
                T.bl_number,
                (
                    SELECT SUM((item ->> 'netWeight')::DECIMAL)
                    FROM jsonb_array_elements(T.data -> 'boeItem') AS item
                ) AS calculated_net_weight,
                (
                    SELECT SUM((item ->> 'grossWeight')::DECIMAL)
                    FROM jsonb_array_elements(T.data -> 'boeItem') AS item
                ) AS calculated_gross_weight,
                jsonb_array_length(T.data -> 'boeItem') AS calculated_total_items
            FROM boe_records T
        """
        params_records = params_base + [limit]
        # Order by boe_date (latest first) for relevance
        sql_records = f"{AGGREGATION_CLAUSE} WHERE {where_clause_str} ORDER BY T.boe_date DESC LIMIT %s;"

        cursor.execute(sql_records, tuple(params_records))
        raw_results = cursor.fetchall()

        def post_process_results(raw_results: List[Tuple]) -> List[Dict[str, Any]]:
            """Formats raw SQL results, injecting core fields and calculated totals into the JSONB data."""
            final_results = []
            for row in raw_results:
                boe_data = row[0].copy() if isinstance(row[0], dict) else row[0]

                # Inject core non-JSONB fields
                boe_data['boe_no'] = row[1]
                boe_data['boe_date'] = row[2].isoformat()
                boe_data['bl_number'] = row[3]

                # Inject calculated totals into the boeHeader section
                if 'boeHeader' in boe_data:
                    boe_data['boeHeader']['calculatedTotalNetWeight'] = float(row[4]) if row[4] else 0.0
                    boe_data['boeHeader']['calculatedTotalGrossWeight'] = float(row[5]) if row[5] else 0.0
                    boe_data['boeHeader']['calculatedTotalItems'] = row[6] if row[6] is not None else 0
                else:
                    # Handle case where boeHeader might be missing (shouldn't happen, but defensive)
                    boe_data['calculatedTotalNetWeight'] = float(row[4]) if row[4] else 0.0
                    boe_data['calculatedTotalGrossWeight'] = float(row[5]) if row[5] else 0.0
                    boe_data['calculatedTotalItems'] = row[6] if row[6] is not None else 0


                final_results.append(boe_data)

            return final_results

        detailed_records = post_process_results(raw_results)

        return {"summary": summary, "records": detailed_records}

    except Exception as e:
        print(f"Error during multi-filter query: {e}")
        raise HTTPException(status_code=500, detail="Internal server error during data retrieval.")

    finally:
        if 'conn' in locals() and conn:
            conn.close()

# ----------------------------------------------
# --- MANIFEST API ENDPOINTS ---
# ----------------------------------------------

def build_manifest_search_query(
    crn: Optional[str], rotation_no: Optional[str], vessel_name: Optional[str], agent_name: Optional[str],
    bl_number: Optional[str], submitted_start_date: date, submitted_end_date: date, limit: int
) -> Tuple[str, List[Any]]:
    """
    Builds the SQL query and parameter list for Manifest search, joining header and BL details.
    Filters by the latest version of the BL.
    """
    
    base_query = """
        SELECT
            -- Header Fields (mh)
            mh.crn, mh.document_type, mh.rotation_no, mh.vessel_name, mh.agent_name,
            mh.eta, mh.etd, mh.last_amended_at,
            mh.document_number, mh.voyage_no, mh.carrier_code, 
            mh.port_of_discharge, mh.port_of_loading,
            
            -- Bill of Lading Fields (mbl) - Exhaustive List
            mbl.bl_number, mbl.bl_version_no, mbl.master_bl_number, 
            mbl.consignee_name, mbl.consignee_address, mbl.shipper_name, 
            mbl.shipper_address, mbl.goods_description, mbl.no_of_containers, mbl.no_of_vehicles, 
            mbl.gross_weight, mbl.volume, mbl.no_of_packages, mbl.unit,
            mbl.imdg_codes, mbl.bl_type, 
            mbl.place_of_receipt, mbl.place_of_delivery, 
            mbl.cargo_type_json, mbl.freight_amount, mbl.submitted_date
            
        FROM
            manifest_header mh
        JOIN
            manifest_bl_details mbl ON mh.crn = mbl.crn
        WHERE
            mbl.latest_bl = TRUE
            AND mbl.submitted_date BETWEEN %s AND %s
    """
    params = [submitted_start_date, submitted_end_date]
    where_clauses = []

    if crn:
        where_clauses.append("mh.crn ILIKE %s")
        params.append(f"%{crn}%")
        
    if rotation_no:
        where_clauses.append("mh.rotation_no ILIKE %s")
        params.append(f"%{rotation_no}%")
        
    if vessel_name:
        where_clauses.append("mh.vessel_name ILIKE %s")
        params.append(f"%{vessel_name}%")
        
    if agent_name:
        where_clauses.append("mh.agent_name ILIKE %s")
        params.append(f"%{agent_name}%")
        
    if bl_number:
        where_clauses.append("mbl.bl_number ILIKE %s")
        params.append(f"%{bl_number}%")
        
    full_query = base_query
    if where_clauses:
        full_query += " AND " + " AND ".join(where_clauses)
        
    full_query += " ORDER BY mh.last_amended_at DESC LIMIT %s;"
    params.append(limit)
    
    return full_query, params

@app.get("/manifests/search", response_model=List[Dict[str, Any]])
async def get_manifest_search(
    submitted_start_date: date = Query(..., description="Manifest Submission Date Start (Inclusive)"),
    submitted_end_date: date = Query(..., description="Manifest Submission Date End (Inclusive)"),
    crn: Optional[str] = Query(None, description="Search by Common Reference Number (CRN)"),
    rotation_no: Optional[str] = Query(None, description="Search by Vessel Rotation Number"),
    vessel_name: Optional[str] = Query(None, description="Search by Vessel Name (Partial match)"),
    agent_name: Optional[str] = Query(None, description="Search by Shipping Agent Name (Partial match)"),
    bl_number: Optional[str] = Query(None, description="Search by Bill of Lading Number (Partial match)"),
    limit: int = Query(100, description="Maximum number of records to return")
):
    """
    🔍 Searches the latest version of Manifests and Bills of Lading (BLs) using multiple filters.
    """
    
    conn = get_api_connection()
    if not conn:
        raise HTTPException(status_code=503, detail="Database service unavailable.")

    try:
        # Build the dynamic SQL query
        sql_command, params = build_manifest_search_query(
            crn, rotation_no, vessel_name, agent_name, bl_number, 
            submitted_start_date, submitted_end_date, limit
        )
        
        # Use DictCursor for easier conversion to dictionary results
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cursor.execute(sql_command, tuple(params))
        
        # Fetch results and convert DictRow to standard dictionary
        results = [dict(row) for row in cursor.fetchall()]
        
        return results

    except psycopg2.Error as e:
        print(f"Database error in /manifests/search: {e}")
        raise HTTPException(status_code=500, detail="An internal database error occurred while querying manifests.")
        
    except Exception as e:
        print(f"General error in /manifests/search: {e}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred during manifest search.")
        
    finally:
        if conn:
            conn.close()

# ----------------------------------------------
# --- DEDICATED ENDPOINT: GET MANIFEST DETAILS (CONTAINERS & VEHICLES) ---
# ----------------------------------------------

@app.get("/manifests/details", response_model=Dict[str, Any])
async def get_manifest_details(
    bl_number: str = Query(..., description="Bill of Lading Number (Exact Match)"),
    bl_version_no: int = Query(..., description="Version Number of the Bill of Lading")
):
    """
    Retrieves all associated container and vehicle details for a specific Bill of Lading and version.
    """
    conn = get_api_connection()
    if not conn:
        raise HTTPException(status_code=503, detail="Database service unavailable.")

    try:
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        results = {"containers": [], "vehicles": []}

        # --- A. Get Container Details ---
        sql_containers = """
            SELECT 
                container_no, seal_number, container_type, container_size, gross_weight, 
                tare_weight, maximum_payload
            FROM 
                manifest_container_details
            WHERE 
                bl_number = %s AND bl_version_no = %s;
        """
        cursor.execute(sql_containers, (bl_number, bl_version_no))
        results["containers"] = [dict(row) for row in cursor.fetchall()]

        # --- B. Get Vehicle Details ---
        sql_vehicles = """
            SELECT 
                chassis_no, model, make
            FROM 
                manifest_vehicle_details
            WHERE 
                bl_number = %s AND bl_version_no = %s;
        """
        cursor.execute(sql_vehicles, (bl_number, bl_version_no))
        results["vehicles"] = [dict(row) for row in cursor.fetchall()]

        if not results["containers"] and not results["vehicles"]:
            # This is a valid 404 case if the BL exists but has no detailed cargo records
            # However, if the BL was found in /manifests/search, it should have some details
            # Raising 404 only if the details are truly expected but missing.
            # Keeping the original 404 logic as it is defensive.
            raise HTTPException(status_code=404, detail=f"No container or vehicle details found for BL: {bl_number} (Version: {bl_version_no}).")

        return results

    except psycopg2.Error as e:
        print(f"Database error in /manifests/details: {e}")
        raise HTTPException(status_code=500, detail="Database error retrieving manifest details.")
        
    except Exception as e:
        if isinstance(e, HTTPException) and e.status_code == 404:
            raise
        print(f"General error in /manifests/details: {e}")
        raise HTTPException(status_code=500, detail="Unexpected error retrieving manifest details.")
        
    finally:
        if conn:
            conn.close()

from typing import Literal

@app.get("/reports/containers-by-range", response_model=Dict[str, List[Dict[str, Any]]])
async def get_containers_by_range_report(
    start_date: date = Query(..., description="BOE Date Start (Inclusive)"),
    end_date: date = Query(..., description="BOE Date End (Inclusive)")
):
    """
    Ghana-Compliant Container Throughput Report (Full Package)
    
    Returns both:
      • "summary": Hierarchical aggregated report with totals (ROLLUP)
      • "details": Full deduplicated container list for audit/verification
    
    Used by: GPHA, Terminal Operators, Shipping Lines, Customs Intelligence
    """
    conn = get_api_connection()
    if not conn:
        raise HTTPException(status_code=503, detail="Database service unavailable.")

    try:
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        params = [start_date, end_date]

        # ===================================================================
        # 1. SUMMARY REPORT (Aggregated with ROLLUP)
        # ===================================================================
        summary_sql = """
        WITH boe_bl AS (
            SELECT DISTINCT
                (data -> 'boeHeader' ->> 'blNumber') AS bl_number
            FROM boe_records
            WHERE boe_date BETWEEN %s AND %s
              AND data -> 'boeHeader' ? 'blNumber'
              AND (data -> 'boeHeader' ->> 'blNumber') IS NOT NULL
        ),
        port_range AS (
            SELECT port_code,
                   COALESCE(NULLIF(TRIM(data ->> 'RangeName'), ''), 'OTHERS') AS range_name
            FROM port_codes
        ),
        dest_port AS (
            SELECT port_code, data ->> 'PortName' AS port_name
            FROM port_codes WHERE port_code IN ('GHTEM', 'GHTKD')
        ),
        container_raw AS (
            SELECT
                mcd.container_no,
                COALESCE(pr.range_name, 'OTHERS') AS range_name,
                COALESCE(dp.port_name, UPPER(br.data -> 'boeHeader' ->> 'portOfDischarge')) AS destination_port,
                CASE
                    WHEN LEFT(mcd.iso_code, 1) = '2' OR LEFT(mcd.iso_code, 2) = '22' THEN '20 FT '
                    ELSE '40 FT '
                END ||
                CASE
                    WHEN mcd.iso_code LIKE '%%G%%' THEN 'DRY'
                    WHEN mcd.iso_code LIKE '%%R%%' THEN 'REEFER'
                    WHEN mcd.iso_code LIKE '%%U%%' THEN 'OPEN TOP'
                    WHEN mcd.iso_code LIKE '%%P%%' THEN 'FLAT RACK'
                    WHEN mcd.iso_code LIKE '%%T%%' THEN 'TANK'
                    WHEN mcd.iso_code LIKE '%%V%%' THEN 'VENTILATED'
                    ELSE 'DRY'
                END AS container_type,
                CASE WHEN LEFT(mcd.iso_code, 1) = '2' THEN 1.0 ELSE 2.0 END AS teus
            FROM manifest_container_details mcd
            JOIN manifest_bl_details mbd
              ON mcd.bl_number = mbd.bl_number AND mcd.bl_version_no = mbd.bl_version_no
            JOIN boe_bl bb ON mbd.bl_number = bb.bl_number
            JOIN boe_records br 
              ON br.data -> 'boeHeader' ->> 'blNumber' = mbd.bl_number
             AND br.boe_date BETWEEN %s AND %s
            LEFT JOIN port_range pr ON (br.data -> 'boeHeader' ->> 'portOfLoading') = pr.port_code
            LEFT JOIN dest_port dp ON (br.data -> 'boeHeader' ->> 'portOfDischarge') = dp.port_code
            WHERE NULLIF(TRIM(mcd.iso_code), '') IS NOT NULL
              AND LENGTH(mcd.iso_code) >= 4
              AND mcd.iso_code ~ '^[A-Z0-9]+$'
        ),
        deduplicated AS (
            SELECT DISTINCT ON (container_no)
                range_name, destination_port, container_type, teus
            FROM container_raw
        ),
        rolled_up AS (
            SELECT
                range_name,
                destination_port,
                container_type,
                COUNT(*)::int AS num_containers,
                SUM(teus)::numeric(12,2) AS total_teus
            FROM deduplicated
            GROUP BY ROLLUP (range_name, destination_port, container_type)
        )
        SELECT
            COALESCE(range_name, 'GRAND TOTAL') AS "Range",
            COALESCE(destination_port, 'ALL PORTS') AS "Port of Destination",
            CASE
                WHEN range_name IS NULL AND container_type IS NULL THEN 'GRAND TOTAL'
                WHEN container_type IS NULL AND destination_port IS NOT NULL THEN 'PORT TOTAL'
                WHEN container_type IS NULL THEN 'RANGE TOTAL'
                ELSE container_type
            END AS "Container Type",
            num_containers AS "Number Of Containers",
            total_teus AS "TEUs"
        FROM rolled_up
        ORDER BY
            CASE WHEN range_name IS NULL THEN 'ZZZZ'
                 WHEN range_name = 'OTHERS' THEN 'ZZZY'
                 ELSE range_name END,
            destination_port NULLS LAST,
            CASE WHEN container_type IS NULL THEN 'ZZZZ'
                 WHEN container_type LIKE '20%%' THEN '01'
                 WHEN container_type LIKE '40%%' THEN '02'
                 ELSE container_type END;
        """

       # ===================================================================
        # 2. DETAILED LIST — NOW INCLUDES COUNTRY (from port_codes)
        # ===================================================================
        details_sql = """
        WITH boe_bl AS (
            SELECT DISTINCT
                (data -> 'boeHeader' ->> 'blNumber') AS bl_number
            FROM boe_records
            WHERE boe_date BETWEEN %s AND %s
              AND data -> 'boeHeader' ? 'blNumber'
        ),
        port_range AS (
            SELECT 
                port_code,
                COALESCE(NULLIF(TRIM(data ->> 'RangeName'), ''), 'OTHERS') AS range_name,
                NULLIF(TRIM(data ->> 'Country'), '') AS country_name
            FROM port_codes
        ),
        dest_port AS (
            SELECT port_code, data ->> 'PortName' AS port_name
            FROM port_codes WHERE port_code IN ('GHTEM', 'GHTKD')
        )
        SELECT
            dedup.container_no                    AS "Container No",
            dedup.iso_code                        AS "ISO Code",
            dedup.container_size                  AS "Manifest Size",
            dedup.original_type                   AS "Manifest Type",
            dedup.bl_number                       AS "BL Number",
            dedup.range_name                      AS "Range",
            dedup.country_name                    AS "Country",        -- NEW FIELD
            dedup.destination_port                AS "Port of Destination",
            dedup.final_type                      AS "Container Type",
            dedup.final_teus::numeric(5,2)        AS "TEUs",
            dedup.vessel_name                     AS "Vessel Name",
            dedup.importer_name                   AS "Importer"
        FROM (
            SELECT
                mcd.container_no,
                mcd.iso_code,
                mcd.container_size,
                mcd.container_type                 AS original_type,
                mbd.bl_number,
                COALESCE(pr.range_name, 'OTHERS')   AS range_name,
                pr.country_name                     AS country_name,     -- NEW: pulled here
                COALESCE(dp.port_name, UPPER(br.data -> 'boeHeader' ->> 'portOfDischarge')) AS destination_port,
                (CASE WHEN LEFT(mcd.iso_code,1)='2' THEN '20 FT ' ELSE '40 FT ' END ||
                 CASE 
                     WHEN mcd.iso_code LIKE '%%G%%' THEN 'DRY'
                     WHEN mcd.iso_code LIKE '%%R%%' THEN 'REEFER'
                     WHEN mcd.iso_code LIKE '%%P%%' THEN 'FLAT RACK'
                     ELSE 'DRY' 
                 END)                               AS final_type,
                (CASE WHEN LEFT(mcd.iso_code,1)='2' THEN 1.0 ELSE 2.0 END) AS final_teus,
                br.data -> 'boeHeader' ->> 'vesselName'    AS vessel_name,
                br.data -> 'boeHeader' ->> 'importerName'  AS importer_name,
                ROW_NUMBER() OVER (PARTITION BY mcd.container_no ORDER BY mbd.submitted_date DESC) AS rn
            FROM manifest_container_details mcd
            JOIN manifest_bl_details mbd
              ON mcd.bl_number = mbd.bl_number AND mcd.bl_version_no = mbd.bl_version_no
            JOIN boe_bl bb ON mbd.bl_number = bb.bl_number
            JOIN boe_records br 
              ON br.data -> 'boeHeader' ->> 'blNumber' = mbd.bl_number
             AND br.boe_date BETWEEN %s AND %s
            LEFT JOIN port_range pr 
              ON (br.data -> 'boeHeader' ->> 'portOfLoading') = pr.port_code
            LEFT JOIN dest_port dp 
              ON (br.data -> 'boeHeader' ->> 'portOfDischarge') = dp.port_code
            WHERE NULLIF(TRIM(mcd.iso_code),'') IS NOT NULL
              AND LENGTH(mcd.iso_code) >= 4
              AND mcd.iso_code ~ '^[A-Z0-9]+$'
        ) dedup
        WHERE dedup.rn = 1
        ORDER BY 
            "Port of Destination", 
            "Range", 
            "Country", 
            "Container Type", 
            "Container No";
        """

        # Keep your summary SQL exactly as it was (it's perfect)
        cursor.execute(summary_sql, params * 2)
        summary = [dict(row) for row in cursor.fetchall()]

        # Now with Country!
        cursor.execute(details_sql, params * 2)
        details = [dict(row) for row in cursor.fetchall()]

        return {
            "summary": summary,
            "details": details
        }

    except Exception as e:
        print(f"Error in containers-by-range report: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate throughput report")
    finally:
        if conn:
            conn.close()

#from datetime import datetime, time # Ensure 'time' is imported

@app.get("/reports/demurrage", response_model=Dict[str, Any])
async def get_demurrage_report(
    # Note: The input type remains datetime, but we will adjust the time inside the function
    start_date: datetime = Query(..., description="BOE Approval Start Date (Inclusive)"),
    end_date: datetime = Query(..., description="BOE Approval End Date (Inclusive)"),
    # Filters
    boe_no: Optional[str] = Query(None, description="Search by Bill of Entry Number (Exact)"),
    importer_tin: Optional[str] = Query(None, description="Search by Importer Tax Identification Number (TIN)"),
    shipping_line_name: Optional[str] = Query(None, description="Search by Shipping Line Name (Partial Match)"),
    hs_code_prefix: Optional[str] = Query(None, description="Search by Item HS Code Prefix (e.g., '8703' for vehicles)"),
    bl_number: Optional[str] = Query(None, description="Search by Bill of Lading Number (Exact Match)"), 
    # Limit
    limit: Optional[int] = Query(None, description="Maximum number of records to return. Default is to return all records.")
):
    """
    Retrieves demurrage and terminal rent costs, ensuring the date range correctly uses 
    start-of-day (00:00:00) and end-of-day (23:59:59) timestamps for accurate filtering.
    """
    conn = get_api_connection()
    if not conn:
        raise HTTPException(status_code=503, detail="Database service unavailable.")

    try:
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        # ------------------------------------------------------------------
        # --- CRITICAL ADJUSTMENT: Padding the dates with correct time ---
        # ------------------------------------------------------------------
        # Set start_date to 00:00:00
        start_timestamp = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Set end_date to 23:59:59.999999 to capture the entire last day
        end_timestamp = end_date.replace(hour=23, minute=59, second=59, microsecond=999999)

        # --- Dynamic WHERE Clause Builder ---
        where_clauses = [
            "b.cargo_type = 'IM'",
            "b.port_of_discharge IN ('Tema', 'Takoradi')",
            "b.package_type IN ('Container', 'Vehicle in Container')",
            # Now using the adjusted timestamps
            "b.boe_approval_date BETWEEN %s AND %s", 
            "b.gate_out_confirmation_date IS NOT NULL",
            "b.final_date_of_discharge IS NOT NULL",
            "b.gate_out_confirmation_date::date >= b.final_date_of_discharge::date"
        ]
        # Use the adjusted timestamps in parameters
        params = [start_timestamp, end_timestamp] 

        if boe_no:
            where_clauses.append("b.boe_no = %s")
            params.append(boe_no)
        
        if importer_tin:
            where_clauses.append("b.importer_tin = %s")
            params.append(importer_tin)
            
        if shipping_line_name:
            where_clauses.append("b.shipping_line_name ILIKE %s")
            params.append(f"%{shipping_line_name}%")

        if hs_code_prefix:
            where_clauses.append("b.item_hs_code LIKE %s")
            params.append(f"{hs_code_prefix}%")
            
        if bl_number: 
            where_clauses.append("b.bl_number = %s")
            params.append(bl_number)

        where_clause_str = " AND ".join(where_clauses)
        
        # --- SQL Query Definition  ---
        DEMURRAGE_RENT_SQL_TEMPLATE = """
            WITH filtered_boe AS (
                SELECT
                    b.boe_no, b.boe_approval_date, b.bl_number, b.importer_name, b.importer_tin, 
                    b.gate_out_confirmation_date, b.final_date_of_discharge, b.port_of_discharge, 
                    b.discharge_terminal, b.package_type, b.item_hs_code, b.shipping_line_name
                FROM boe_header b
                WHERE {where_clause} 
            ),
            boe_costs AS (
                SELECT
                    b.boe_no, MAX(b.boe_approval_date) AS boe_approval_date, MAX(b.bl_number) AS bl_number,
                    MAX(b.importer_name) AS importer_name, MAX(b.importer_tin) AS importer_tin,
                    MAX(b.gate_out_confirmation_date) AS gate_out_confirmation_date, 
                    MAX(b.final_date_of_discharge) AS final_date_of_discharge, 
                    MAX(b.port_of_discharge) AS port_of_discharge, MAX(b.discharge_terminal) AS terminal,
                    MAX(b.package_type) AS package_type, MAX(b.item_hs_code) AS hs_code, 
                    MAX(b.shipping_line_name) AS shipping_line_name,
                    
                    -- DURATION: Uses ::date cast as required
                    (MAX(b.gate_out_confirmation_date)::date - MAX(b.final_date_of_discharge)::date) AS duration_days,
                    
                    -- 1. Demurrage (USD)
                    CASE
                        WHEN (MAX(b.gate_out_confirmation_date)::date - MAX(b.final_date_of_discharge)::date) < 8 THEN 0
                        WHEN (MAX(b.gate_out_confirmation_date)::date - MAX(b.final_date_of_discharge)::date) <= 14
                             THEN (MAX(b.gate_out_confirmation_date)::date - MAX(b.final_date_of_discharge)::date - 7) * 22
                        WHEN (MAX(b.gate_out_confirmation_date)::date - MAX(b.final_date_of_discharge)::date) <= 21
                             THEN (MAX(b.gate_out_confirmation_date)::date - MAX(b.final_date_of_discharge)::date - 14) * 33 + 154
                        ELSE (MAX(b.gate_out_confirmation_date)::date - MAX(b.final_date_of_discharge)::date - 21) * 50 + 385
                    END AS demurrage_usd,

                    -- 2. Total Rent (GHC)
                    CASE 
                        WHEN MAX(b.package_type) = 'Container' THEN
                            CASE
                                WHEN (MAX(b.gate_out_confirmation_date)::date - MAX(b.final_date_of_discharge)::date) < 8 THEN 0
                                WHEN (MAX(b.gate_out_confirmation_date)::date - MAX(b.final_date_of_discharge)::date) <= 14
                                    THEN (MAX(b.gate_out_confirmation_date)::date - MAX(b.final_date_of_discharge)::date - 7) * 17.78
                                WHEN (MAX(b.gate_out_confirmation_date)::date - MAX(b.final_date_of_discharge)::date) <= 21
                                    THEN (MAX(b.gate_out_confirmation_date)::date - MAX(b.final_date_of_discharge)::date - 14) * 38.02 + 124.46
                                ELSE (MAX(b.gate_out_confirmation_date)::date - MAX(b.final_date_of_discharge)::date - 21) * 127.91 + 390.6
                            END
                        WHEN MAX(b.package_type) = 'Vehicle in Container' THEN
                            CASE
                                WHEN (MAX(b.gate_out_confirmation_date)::date - MAX(b.final_date_of_discharge)::date) < 8 THEN 0
                                WHEN (MAX(b.gate_out_confirmation_date)::date - MAX(b.final_date_of_discharge)::date) <= 14
                                    THEN (MAX(b.gate_out_confirmation_date)::date - MAX(b.final_date_of_discharge)::date - 7) * 11.86
                                WHEN (MAX(b.gate_out_confirmation_date)::date - MAX(b.final_date_of_discharge)::date) <= 21
                                    THEN (MAX(b.gate_out_confirmation_date)::date - MAX(b.final_date_of_discharge)::date - 14) * 19.84 + 83.02
                                ELSE (MAX(b.gate_out_confirmation_date)::date - MAX(b.final_date_of_discharge)::date - 21) * 67.72 + 221.9
                            END
                        ELSE 0.00
                    END AS total_rent_ghc
                    
                FROM filtered_boe b
                GROUP BY b.boe_no
                HAVING (MAX(b.gate_out_confirmation_date)::date - MAX(b.final_date_of_discharge)::date) >= 0
            )
            SELECT 
                boe_no, boe_approval_date, bl_number, importer_name, importer_tin, gate_out_confirmation_date, 
                final_date_of_discharge, port_of_discharge, terminal, hs_code, shipping_line_name, 
                package_type, duration_days, total_rent_ghc, demurrage_usd
            FROM boe_costs
            ORDER BY duration_days ASC
        """
        
        final_sql = DEMURRAGE_RENT_SQL_TEMPLATE.format(where_clause=where_clause_str)
        
        # --- Conditional LIMIT Logic ---
        if limit is not None and limit > 0:
            final_sql += " LIMIT %s;"
            params.append(limit)
        else:
            final_sql += ";"

        # Execute query with adjusted timestamps
        cursor.execute(final_sql, tuple(params))
        raw_results = cursor.fetchall()

        # --- Aggregation and Response Formatting  ---
        total_demurrage_usd = 0.0
        total_rent_ghc = 0.0
        total_container_rent_ghc = 0.0
        total_vehicle_rent_ghc = 0.0
        count_container_boe = 0
        count_vehicle_boe = 0
        
        for row in raw_results:
            demurrage = float(row['demurrage_usd'])
            rent = float(row['total_rent_ghc'])
            package_type = row['package_type']

            total_demurrage_usd += demurrage
            total_rent_ghc += rent
            
            if package_type == 'Container':
                total_container_rent_ghc += rent
                count_container_boe += 1
            elif package_type == 'Vehicle in Container':
                total_vehicle_rent_ghc += rent
                count_vehicle_boe += 1

        response = {
            "summary": {
                "total_boe_records": len(raw_results),
                "total_demurrage_usd": round(total_demurrage_usd, 2),
                "total_rent_ghc": round(total_rent_ghc, 2),
                "rent_details": {
                    "total_container_rent_ghc": round(total_container_rent_ghc, 2),
                    "count_container_boe": count_container_boe,
                    "total_vehicle_rent_ghc": round(total_vehicle_rent_ghc, 2),
                    "count_vehicle_boe": count_vehicle_boe
                }
            },
            "records": [
                {
                    'boe_no': row['boe_no'],
                    'boe_approval_date': row['boe_approval_date'],
                    'bl_number': row['bl_number'],
                    'importer_name': row['importer_name'],
                    'importer_tin': row['importer_tin'],
                    'gate_out_confirmation_date': row['gate_out_confirmation_date'],
                    'final_date_of_discharge': row['final_date_of_discharge'],
                    'port_of_discharge': row['port_of_discharge'],
                    'terminal': row['terminal'],
                    'hs_code': row['hs_code'],
                    'shipping_line_name': row['shipping_line_name'],
                    'package_type': row['package_type'],
                    'duration_days': row['duration_days'],
                    'demurrage_usd': round(float(row['demurrage_usd']), 2), 
                    'total_rent_ghc': round(float(row['total_rent_ghc']), 2),
                } for row in raw_results
            ]
        }
        
        return response

    except psycopg2.Error as e:
        print(f"Database error in /reports/demurrage: {e}")
        raise HTTPException(status_code=500, detail="Database error during demurrage report generation.")
        
    except Exception as e:
        print(f"General error in /reports/demurrage: {e}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")
        
    finally:
        if conn:
            conn.close()

@app.get("/health")
async def health_check():
    """Simple health check endpoint."""
    return {"status": "ok", "service": "BOE API"}