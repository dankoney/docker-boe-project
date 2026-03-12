import os
import streamlit as st
import requests
import datetime
import pandas as pd
import html
from typing import Dict, Any, Optional
import altair as alt
import sys
from pathlib import Path
import gc
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.auth_api import get_cookie_manager, restore_from_cookie, is_authenticated

# Cookie-based auth: restore session from cookie so Demurrage works after login or reload
cookies = get_cookie_manager()
if not cookies.ready():
    st.stop()
if not is_authenticated():
    restore_from_cookie(cookies)
if not is_authenticated():
    st.warning("Please sign in on the Home page to access the reports.")
    st.page_link("Home.py", label="Go to Sign in", icon="🏠")
    st.stop()

# Optional: Hydralit Components for modern menus/buttons
try:
    import hydralit_components as hc
    HYDRALIT_AVAILABLE = True
except ImportError:
    HYDRALIT_AVAILABLE = False

# Apply modern admin theme

# API base URL: set API_BASE_URL env var in Docker (e.g. http://api:8000)
_API_BASE = os.environ.get("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
# Suggestion endpoints
HSCODE_SUGGEST_ENDPOINT = f"{_API_BASE}/hscodes/suggestions"
VESSEL_SUGGEST_ENDPOINT = f"{_API_BASE}/suggestions/vessel"
IMPORTER_SUGGEST_ENDPOINT = f"{_API_BASE}/suggestions/importer"

# Configuration
FASTAPI_DEMURRAGE_ENDPOINT = f"{_API_BASE}/reports/demurrage"

# Vibrant color scheme for charts (works well in both light and dark modes)
VIBRANT_COLORS = [
'#1E3A8A', # Dark Blue (primary org color)
'#FFD700', # Gold (secondary org color)
'#FF6B6B', # Light Red (accent org color)
'#2563EB', # Blue (variant of dark blue)
'#F59E0B', # Amber (variant of gold)
'#EF4444', # Red (variant of light red)
'#3B82F6', # Blue Light
'#FCD34D', # Yellow Light
'#DC2626', # Red Dark
'#1D4ED8'  # Blue Dark
]

# Line chart colors
LINE_COLORS = {
    'secondary': '#FFD700',  # Gold for secondary metric
    'tertiary': '#FF6B6B',  # Light Red for tertiary metric
    'primary': '#FF6B6B'  # Coral Red for primary metric
}


def collect_params(start_dt: datetime.datetime, end_dt: datetime.datetime) -> Dict[str, Any]:
    params: Dict[str, Any] = {
        "start_date": str(start_dt.date()),
        "end_date": str(end_dt.date()),
    }
    # Optional filters
    boe_no = st.session_state.get('dem_boe_no', '').strip()
    importer_tin = st.session_state.get('dem_importer_tin', '').strip()
    shipping_line_name = st.session_state.get('dem_shipping_line', '').strip()
    hs_code_prefix = st.session_state.get('dem_hs_code', '').strip()
    bl_number = st.session_state.get('dem_bl_number', '').strip()
    if boe_no:
        params['boe_no'] = boe_no
    if importer_tin:
        params['importer_tin'] = importer_tin
    if shipping_line_name:
        params['shipping_line_name'] = shipping_line_name
    selected_hscodes = st.session_state.get('selected_hscodes', [])
    if selected_hscodes:
        params['hs_code_prefix'] = selected_hscodes[0]
    elif hs_code_prefix:
        params['hs_code_prefix'] = hs_code_prefix
    selected_vessels = st.session_state.get('selected_vessel_names', [])
    if selected_vessels and not params.get('shipping_line_name'):
        params['shipping_line_name'] = selected_vessels[0]
    selected_importers = st.session_state.get('selected_importer_names', [])
    if selected_importers and not params.get('importer_tin'):
        suggs = st.session_state.get('importer_suggestions', [])
        found_tin = None
        for s in suggs:
            name = s.get('name')
            tin = s.get('importerTin')
            if name and name in selected_importers and tin:
                found_tin = tin
                break
        if found_tin:
            params['importer_tin'] = found_tin
        else:
            if selected_importers:
                params['importer_tin'] = selected_importers[0]
    if bl_number:
        params['bl_number'] = bl_number
    return params


def run_demurrage_search(params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        # Add memory cleanup before API call
        gc.collect()
        
        # Show searching message
        search_placeholder = st.empty()
        search_placeholder.info("🔍 Searching records... This may take a moment for large datasets.")
        
        resp = requests.get(FASTAPI_DEMURRAGE_ENDPOINT, params=params, timeout=300)
        resp.raise_for_status()
        
        result = resp.json()
        
        # Clear searching message
        search_placeholder.empty()
        
        # Clean up memory after successful response
        gc.collect()
        
        return result
    except requests.exceptions.Timeout:
        st.error("⏱️ Request timed out. Please try with a smaller date range or fewer filters.")
        return None
    except requests.exceptions.ConnectionError:
        st.error("🔌 Cannot connect to API server. Please check if the API is running.")
        return None
    except requests.exceptions.RequestException as e:
        st.error(f"❌ API request failed: {e}")
        return None
    except Exception as e:
        st.error(f"💥 Unexpected error: {e}")
        st.error("Please try refreshing the page or contact support.")
        return None


# ------------------ Suggestions helpers ------------------
def fetch_hscode_suggestions(search_term: str):
    if len(search_term) >= 4:
        try:
            response = requests.get(f"{HSCODE_SUGGEST_ENDPOINT}?prefix={search_term}")
            response.raise_for_status()
            st.session_state['hscode_suggestions'] = response.json()
        except requests.exceptions.RequestException:
            st.session_state['hscode_suggestions'] = []
    else:
        st.session_state['hscode_suggestions'] = []


def fetch_keyword_suggestions(search_term: str, endpoint: str, state_key: str):
    if len(search_term) >= 3:
        try:
            response = requests.get(f"{endpoint}?keyword={search_term}")
            response.raise_for_status()
            st.session_state[state_key] = response.json()
        except requests.exceptions.RequestException:
            st.session_state[state_key] = []
    else:
        st.session_state[state_key] = []


def _on_keyword_submit(endpoint_url: str, suggestions_state_key: str, input_key: str):
    cur = st.session_state.get(input_key, '').strip()
    if cur:
        fetch_keyword_suggestions(cur, endpoint_url, suggestions_state_key)
    else:
        st.session_state[suggestions_state_key] = []


def _on_hscode_submit():
    cur = st.session_state.get('hscode_search_input', '').strip()
    if len(cur) >= 4:
        fetch_hscode_suggestions(cur)
    else:
        st.session_state['hscode_suggestions'] = []


def render_suggestion_section(title, input_key, suggestions_state_key, selected_state_key, endpoint_url, min_length):
    clear_flag_key = f'clear_{input_key}'
    if st.session_state.get(clear_flag_key):
        st.session_state[input_key] = ''
        del st.session_state[clear_flag_key]
    st.markdown(f"**Search {title}**")
    st.markdown('<div class="stCustomAlignedInput">', unsafe_allow_html=True)
    col_input, col_add = st.columns([3, 1])
    with col_input:
        st.text_input(
            "__HIDDEN_INPUT__",
            key=input_key,
            label_visibility='collapsed',
            placeholder=f"Enter {title} or search keyword",
            on_change=lambda: _on_keyword_submit(endpoint_url, suggestions_state_key, input_key) if endpoint_url else _on_hscode_submit()
        )
    with col_add:
        current_input = st.session_state.get(input_key, '').strip()
        if st.button(f"+ Add", key=f"add_{input_key}", disabled=(len(current_input) < min_length), use_container_width=True):
            if current_input and current_input not in st.session_state[selected_state_key]:
                st.session_state[selected_state_key].append(current_input)
                st.session_state[clear_flag_key] = True
                st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)
    suggestions = st.session_state.get(suggestions_state_key, [])
    if suggestions:
        st.markdown("**i\uFE0F Suggestions:**")
        with st.container():
            col_sugg = st.columns(3)
            for idx, item in enumerate(suggestions):
                main_str = item.get('hscode') or item.get('name')
                display_text = ""
                tooltip_text = ""
                if 'hscode' in item:
                    secondary_info = item.get('description', 'No Desc.')
                    display_text = f"**{main_str}** - {secondary_info[:30]}..."
                    tooltip_text = f"HS Code: {main_str} - Description: {secondary_info}"
                elif 'vesselNationality' in item:
                    code = item.get('vesselNationality', '').upper()
                    display_text = f"**{main_str}** ({code})"
                    tooltip_text = f"Vessel: {main_str} - Nationality: {code}"
                elif 'importerTin' in item:
                    tin = item.get('importerTin', 'N/A')
                    display_text = f"**{main_str}** ({tin})"
                    tooltip_text = f"Importer: {main_str} - TIN: {tin}"
                is_selected = main_str in st.session_state[selected_state_key]
                key_name = f"{selected_state_key}_suggest_{main_str}_{idx}"
                with col_sugg[idx % 3]:
                    checked = st.checkbox(display_text, value=is_selected, key=key_name, help=tooltip_text)
                    if checked and not is_selected:
                        st.session_state[selected_state_key].append(main_str)
                        st.rerun()
                    if not checked and is_selected:
                        try:
                            st.session_state[selected_state_key].remove(main_str)
                        except ValueError:
                            pass
                        st.rerun()
    if st.session_state.get(selected_state_key):
        st.markdown("**Selected Terms**")
        final_list = st.multiselect(
            f"Selected {title} Terms",
            options=st.session_state[selected_state_key],
            default=st.session_state[selected_state_key],
            key=f'{selected_state_key}_final_list_widget'
        )
        st.session_state[selected_state_key] = final_list


# ----------------------------------------------------------------------------------------
def render_summary(summary: Dict[str, Any]):
    st.markdown("### Summary")
    col1, col2, col3 = st.columns(3)
    col1.metric("Total BOE Records", f"{summary.get('total_boe_records', 0)}")
    col2.metric("Total Demurrage (USD)", f"{summary.get('total_demurrage_usd', 0):,.2f}")
    col3.metric("Total Rent (GHC)", f"{summary.get('total_rent_ghc', 0):,.2f}")
    rent_details = summary.get('rent_details', {})
    with st.expander("Rent Details"):
        st.write(rent_details)


def render_modern_pagination(current_page: int, total_pages: int, page_size: int) -> tuple:
    """Render modern pagination controls and return updated page info"""
    
    # Calculate page range to show
    max_visible = 7  # Number of page buttons to show
    half_visible = max_visible // 2
    
    if total_pages <= max_visible:
        start_page = 1
        end_page = total_pages
    else:
        if current_page <= half_visible:
            start_page = 1
            end_page = max_visible
        elif current_page >= total_pages - half_visible:
            start_page = total_pages - max_visible + 1
            end_page = total_pages
        else:
            start_page = current_page - half_visible
            end_page = current_page + half_visible
    
    # Pagination controls container
    st.markdown("---")
    
    # Page size selector and info
    col1, col2, col3 = st.columns([2, 3, 2])
    with col1:
        new_page_size = st.selectbox(
            "📄 Records per page",
            options=[50, 100, 200, 500, 1000],
            index=1,
            key="page_size_selector",
            format_func=lambda x: f"{x:,} records"
        )
    
    with col2:
        st.markdown(f"""
        <div style='text-align: center; padding: 10px;'>
            <strong>Page {current_page:,} of {total_pages:,}</strong> | 
            Total Records: <span style='color: #1E3A8A;'>{st.session_state.get('total_records', 0):,}</span>
        </div>
        """, unsafe_allow_html=True)
        
    
    with col3:
        st.markdown("")  # Empty space for layout balance
    
    # Calculate the total number of buttons needed
    button_count = 2  # Previous + Next buttons
    
    # Add first page button if not in range
    if start_page > 1:
        button_count += 1  # First page button
        if start_page > 2:
            button_count += 1  # Ellipsis
    
    # Add page range buttons
    button_count += (end_page - start_page + 1)
    
    # Add last page button if not in range
    if end_page < total_pages:
        if end_page < total_pages - 1:
            button_count += 1  # Ellipsis
        button_count += 1  # Last page button
    
    # Create columns for pagination buttons
    button_cols = st.columns([1] * button_count)
    
    col_idx = 0
    
    # Previous button
    with button_cols[col_idx]:
        if st.button("⬅️", key="prev_page", disabled=current_page == 1, use_container_width=True):
            st.session_state.current_page = max(1, current_page - 1)
            st.rerun()
    col_idx += 1
    
    # First page with ellipsis
    if start_page > 1:
        with button_cols[col_idx]:
            if st.button("1", key="page_1", use_container_width=True):
                st.session_state.current_page = 1
                st.rerun()
        col_idx += 1
        
        if start_page > 2:
            with button_cols[col_idx]:
                st.markdown('<div style="padding: 8px;">...</div>', unsafe_allow_html=True)
            col_idx += 1
    
    # Page number buttons
    for page_num in range(start_page, end_page + 1):
        with button_cols[col_idx]:
            button_style = "primary" if page_num == current_page else "secondary"
            if st.button(str(page_num), key=f"page_{page_num}", use_container_width=True, type=button_style):
                st.session_state.current_page = page_num
                st.rerun()
        col_idx += 1
    
    # Last page with ellipsis
    if end_page < total_pages:
        if end_page < total_pages - 1:
            with button_cols[col_idx]:
                st.markdown('<div style="padding: 8px;">...</div>', unsafe_allow_html=True)
            col_idx += 1
        
        with button_cols[col_idx]:
            if st.button(str(total_pages), key=f"page_{total_pages}", use_container_width=True):
                st.session_state.current_page = total_pages
                st.rerun()
        col_idx += 1
    
    # Next button
    with button_cols[col_idx]:
        if st.button("➡️", key="next_page", disabled=current_page >= total_pages, use_container_width=True):
            st.session_state.current_page = min(total_pages, current_page + 1)
            st.rerun()
    
    # Quick navigation stats
    st.markdown(f"""
    <div style='background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                color: white; padding: 15px; border-radius: 10px; text-align: center; margin: 10px 0;'>
        <strong>📊 Navigation Stats:</strong> 
        Showing {((current_page-1)*page_size)+1:,} - {min(current_page*page_size, st.session_state.get('total_records', 0)):,} 
        of {st.session_state.get('total_records', 0):,} records
    </div>
    """, unsafe_allow_html=True)
    
    return current_page, new_page_size


def render_records_table(records: list, apply_package_filter: bool = False):
    if not records:
        st.warning("No records returned for the selected criteria.")
        return
    
    total_records = len(records)
    st.session_state.total_records = total_records
    
    # For large datasets, use modern pagination
    if total_records > 1000:
        st.info(f"📊 Total dataset ({total_records:,} records).")
        
        # Get pagination settings
        current_page = st.session_state.get('current_page', 1)
        page_size = st.session_state.get('page_size_selector', 100)
        
        total_pages = (total_records + page_size - 1) // page_size
        current_page = min(max(1, current_page), total_pages)
        
        # Render modern pagination controls
        current_page, page_size = render_modern_pagination(current_page, total_pages, page_size)
        
        # Get current page data
        start_idx = (current_page - 1) * page_size
        end_idx = min(start_idx + page_size, total_records)
        page_records = records[start_idx:end_idx]
        
        df = pd.DataFrame(page_records)
    else:
        # Small datasets - show all at once
        st.info(f"📋 Small dataset ({total_records:,} records). Showing all records.")
        df = pd.DataFrame(records)
    
    # Apply package type filter if requested
    if apply_package_filter and not df.empty:
        df = apply_package_type_filter(df)
    
    # Optimize memory
    df = df.copy()
    
    # Display columns
    display_cols = [
        'boe_no', 'boe_approval_date', 'bl_number', 'importer_name', 'importer_tin',
        'gate_out_confirmation_date', 'final_date_of_discharge', 'port_of_discharge', 'terminal',
        'hs_code', 'shipping_line_name', 'package_type', 'duration_days', 'demurrage_usd', 'total_rent_ghc'
    ]
    cols = [c for c in display_cols if c in df.columns]
    
    # Show data table with modern styling
    if cols:
        st.dataframe(df[cols], use_container_width=True, hide_index=True)
    else:
        st.dataframe(df, use_container_width=True, hide_index=True)
    
    # Download section
    if total_records > 1000:
        st.markdown("---")
        col_download1, col_download2, col_download3 = st.columns([1, 2, 1])
        with col_download2:
            st.markdown("### 📥 Download Options")
            
            try:
                # Full dataset download
                full_df = pd.DataFrame(records)
                csv_full = full_df.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label='📊 Download Complete Dataset (CSV)',
                    data=csv_full,
                    file_name=f'demurrage_report_full_{total_records}_records.csv',
                    mime='text/csv',
                    use_container_width=True
                )
                
                # Current page download
                csv_page = df.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label='📄 Download Current Page (CSV)',
                    data=csv_page,
                    file_name=f'demurrage_report_page_{current_page}_{total_pages}.csv',
                    mime='text/csv',
                    use_container_width=True
                )
                
                del full_df
            except Exception as e:
                st.error(f'Download not available: {e}')
    
    # Memory cleanup
    del df
    gc.collect()


# ------------------ Data aggregation helpers ------------------
def ensure_df(records: list) -> pd.DataFrame:
    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records)
    for col in ['boe_approval_date', 'gate_out_confirmation_date', 'final_date_of_discharge']:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors='coerce')
    if 'demurrage_usd' in df.columns:
        df['demurrage_usd'] = pd.to_numeric(df['demurrage_usd'], errors='coerce').fillna(0.0)
    if 'total_rent_ghc' in df.columns:
        df['total_rent_ghc'] = pd.to_numeric(df['total_rent_ghc'], errors='coerce').fillna(0.0)
    if 'duration_days' in df.columns:
        df['duration_days'] = pd.to_numeric(df['duration_days'], errors='coerce').fillna(0).astype(int)
    if 'hs_code' in df.columns:
        df['hs4'] = df['hs_code'].astype(str).str[:4]
    if 'importer_name' in df.columns or 'importer_tin' in df.columns:
        def _make_label(row):
            name = str(row.get('importer_name') or '').strip()
            tin = str(row.get('importer_tin') or '').strip()
            if name and tin:
                return f"{name} ({tin})"
            if name:
                return name
            if tin:
                return tin
            return 'N/A'
        df['importer_label'] = df.apply(_make_label, axis=1)
    return df


def duration_buckets(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or 'duration_days' not in df.columns:
        return df
    bins = [0, 7, 14, 21, 10000]
    labels = ['0-7', '8-14', '15-21', '22+']
    df = df.copy()
    df['duration_bucket'] = pd.cut(df['duration_days'], bins=bins, labels=labels, right=True)
    return df


def apply_package_type_filter(df: pd.DataFrame) -> pd.DataFrame:
    """
    Apply package type-based demurrage calculation.
    - Container: only calculate demurrage for 0-21 duration days
    - Vehicle in Container: only calculate demurrage for 0-60 duration days
    """
    if df.empty:
        return df
    
    df_filtered = df.copy()
    
    # For containers: only include records with 0-21 duration days
    container_mask = (df_filtered['package_type'].str.lower() == 'container') & (df_filtered['duration_days'] <= 21)
    
    # For vehicles in container: only include records with 0-60 duration days  
    vehicle_mask = (df_filtered['package_type'].str.lower() == 'vehicle in container') & (df_filtered['duration_days'] <= 60)
    
    # Apply the filter - keep only records that match the criteria
    df_filtered = df_filtered[container_mask | vehicle_mask]
    
    return df_filtered


def group_operational(df: pd.DataFrame, value_col: str, group_field: str, top_n: int = 10) -> pd.DataFrame:
    if df.empty or group_field not in df.columns:
        return pd.DataFrame()
    out = df.groupby(group_field).agg(total_value=(value_col, 'sum'), count=('boe_no', 'nunique')).reset_index()
    out = out.sort_values('total_value', ascending=False).head(top_n)
    return out


# --------------------------------------------------------------------------------
# FIXED: Safe Altair chart that disables all Vega actions (including "Show data")
def safe_altair_chart(chart, height=320):
    """
    Displays Altair chart with perfect hover tooltips.
    Completely disables Vega actions menu (including "Show data") so you NEVER get stuck in table mode.
    """
    st.altair_chart(
        chart.properties(height=height),
        use_container_width=True,
        theme="streamlit"
    )


def render_explain_expander(explanation: str, key: str, title: str = "Explain"):
    with st.expander(f"ℹ️ {title}", expanded=False):
        st.markdown(explanation)


def inject_expander_css() -> None:
    if st.session_state.get('expander_css_injected'):
        return
    css = """
    <style>
    .stExpander, .st-expander, .streamlit-expander {
        border: 1px solid var(--secondary-background) !important;
        background: var(--secondary-background) !important;
        border-radius: 8px !important;
        margin-bottom: 8px !important;
    }
    .streamlit-expanderHeader, .stExpander summary {
        color: var(--primary-color) !important;
    }
    </style>
    """
    st.markdown(css, unsafe_allow_html=True)
    st.session_state['expander_css_injected'] = True


def demurrage_page():
    st.title("Demurrage & Terminal Rent Report")
    st.markdown("""
    Use this report to find demurrage and terminal rent for BOE records. Select a date/time range and optional filters.
    """)
    
    # ==== SESSION STATE INITIALIZATION ====
    init_defaults = {
        'dem_boe_no': '',
        'dem_importer_tin': '',
        'dem_shipping_line': '',
        'dem_hs_code': '',
        'dem_bl_number': '',
        'hscode_search_input': '',
        'vessel_search_input': '',
        'importer_search_input': '',
        'hscode_suggestions': [],
        'vessel_suggestions': [],
        'importer_suggestions': [],
        'selected_hscodes': [],
        'selected_vessel_names': [],
        'selected_importer_names': [],
        'df_raw': pd.DataFrame(),
        'summary': {},
        'dem_drilldown_filter': {},
        'rent_drilldown_filter': {},
        'time_granularity': 'Month',
        'selected_time_periods': [],
        'package_type_filter_enabled': False,
        'selected_package_type': 'All'
    }
    for key, default in init_defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default

    # Clear filters handling
    if st.session_state.get('clear_widgets_flag', False):
        for key in init_defaults:
            if key not in ['df_raw', 'summary', 'dem_drilldown_filter', 'rent_drilldown_filter']:
                st.session_state[key] = init_defaults[key]
        st.session_state['clear_widgets_flag'] = False

    now = datetime.datetime.now()
    default_start = now - datetime.timedelta(days=30)

    with st.expander("🔍 Define Search Criteria", expanded=True):
        st.markdown("### Date Range (Required)")
        col_date_from, col_date_to = st.columns(2)
        with col_date_from:
            start_date = st.date_input("Start Date", key='dem_start_date', value=default_start.date())
        with col_date_to:
            end_date = st.date_input("End Date", key='dem_end_date', value=now.date())

        tab_doc_no, tab_item_hscode, tab_vessel, tab_importer = st.tabs(["Document Numbers", "Item & HS Code", "Vessel/Shipping Line", "Importer Details"])
        with tab_doc_no:
            st.text_input('BOE Number (exact)', key='dem_boe_no')
            st.text_input('BL Number (exact)', key='dem_bl_number')
            st.text_input('Importer TIN', key='dem_importer_tin')
        with tab_item_hscode:
            render_suggestion_section(title="HS Code", input_key='hscode_search_input',
                                      suggestions_state_key='hscode_suggestions', selected_state_key='selected_hscodes',
                                      endpoint_url=None, min_length=4)
        with tab_vessel:
            render_suggestion_section(title="Shipping Line / Vessel", input_key='vessel_search_input',
                                      suggestions_state_key='vessel_suggestions', selected_state_key='selected_vessel_names',
                                      endpoint_url=VESSEL_SUGGEST_ENDPOINT, min_length=3)
        with tab_importer:
            render_suggestion_section(title="Importer", input_key='importer_search_input',
                                      suggestions_state_key='importer_suggestions', selected_state_key='selected_importer_names',
                                      endpoint_url=IMPORTER_SUGGEST_ENDPOINT, min_length=3)

        start_dt = datetime.datetime.combine(start_date, datetime.time.min)
        end_dt = datetime.datetime.combine(end_date, datetime.time.max)

    # Search and Clear buttons
    col_search, col_clear = st.columns([1, 1])
    if col_search.button('Run Demurrage Search'):
        params = collect_params(start_dt, end_dt)
        with st.spinner('Querying demurrage data...'):
            result = run_demurrage_search(params)
        if result is None:
            st.error('❌ Search failed. Please check your filters and try again.')
            return
        
        # Check if search returned data
        records = result.get('records', [])
        summary = result.get('summary', {})
        
        if not records:
            st.warning('🔍 No records found matching your search criteria.')
            st.info('💡 Try adjusting your filters:')
            st.markdown('- **Expand date range**: Try a broader time period')
            st.markdown('- **Reduce filters**: Remove some search criteria')
            st.markdown('- **Check data availability**: Verify data exists for the selected period')
            return
        
        # Success feedback
        record_count = len(records)
        total_dem = summary.get('total_demurrage_usd', 0)
        st.success(f'✅ Found {record_count:,} records with total demurrage of ${total_dem:,.2f}')
        
        st.session_state.summary = summary
        st.session_state.df_raw = ensure_df(records)

    if col_clear.button('Clear Filters'):
        st.session_state['clear_widgets_flag'] = True
        st.rerun()

    # Load data from session state
    df_raw = st.session_state.df_raw
    summary = st.session_state.summary
    if df_raw.empty:
        st.warning("Run search to load data.")
        return

    # === TIME DRILL-DOWN SECTION ===
    st.markdown("### Time Period Drill-Down")
    col_gran, col_clear_time = st.columns([2, 1])
    with col_gran:
        granularity = st.selectbox(
            "Select Time Granularity",
            options=['Day', 'Month', 'Quarter', 'Year'],
            index=['Day', 'Month', 'Quarter', 'Year'].index(st.session_state.time_granularity),
            key='time_granularity_widget'
        )
        st.session_state.time_granularity = granularity
    with col_clear_time:
        if st.button("Clear Time Filter"):
            st.session_state.time_granularity = 'Month'
            st.session_state.selected_time_periods = []
            st.rerun()

    # Generate available periods based on current data
    available_periods = []
    cleaned_selected_periods = []

    if 'boe_approval_date' in df_raw.columns and not df_raw.empty:
        df_dates = pd.to_datetime(df_raw['boe_approval_date'], errors='coerce', utc=True)
        df_dates = df_dates.dropna()
        dates = df_dates.dt.date.unique()
        dates = sorted(dates)

        if granularity == 'Day':
            available_periods = dates
            format_func = lambda x: x.strftime('%Y-%m-%d')
        elif granularity == 'Month':
            months = sorted(set((d.year, d.month) for d in dates))
            available_periods = [datetime.date(y, m, 1) for y, m in months]
            format_func = lambda x: x.strftime('%Y-%m')
        elif granularity == 'Quarter':
            quarters = sorted(set((d.year, (d.month - 1) // 3 + 1) for d in dates))
            available_periods = [f"{y}-Q{q}" for y, q in quarters]
            format_func = lambda x: x
        else:  # Year
            available_periods = sorted(set(d.year for d in dates))
            format_func = lambda x: str(x)

        # Clean previously selected periods: keep only those still available
        previous_selections = st.session_state.get('selected_time_periods', [])
        for prev in previous_selections:
            if prev in available_periods:
                cleaned_selected_periods.append(prev)

        # Update session state with cleaned selection
        st.session_state.selected_time_periods = cleaned_selected_periods

        # Now safely use multiselect with valid defaults
        selected_periods = st.multiselect(
            f"Select {granularity}(s)",
            options=available_periods,
            default=cleaned_selected_periods,
            format_func=format_func,
            key='time_period_widget'
        )
    else:
        st.info("No date data available for time drill-down.")
        selected_periods = []
        st.session_state.selected_time_periods = []

    # Apply time filter
    df_filtered = df_raw.copy()
    if selected_periods:
        if granularity == 'Day':
            df_filtered = df_filtered[pd.to_datetime(df_filtered['boe_approval_date'], utc=True).dt.date.isin(selected_periods)]
        elif granularity == 'Month':
            selected_month_tuples = [(d.year, d.month) for d in selected_periods]
            df_filtered = df_filtered[
                pd.to_datetime(df_filtered['boe_approval_date'], utc=True).apply(
                    lambda x: (x.year, x.month) if pd.notnull(x) else None
                ).isin(selected_month_tuples)
            ]
        elif granularity == 'Quarter':
            selected_q_tuples = [tuple(map(int, q.split('-Q'))) for q in selected_periods]
            df_filtered = df_filtered[
                pd.to_datetime(df_filtered['boe_approval_date'], utc=True).apply(
                    lambda x: (x.year, (x.month-1)//3 + 1) if pd.notnull(x) else None
                ).isin(selected_q_tuples)
            ]
        else:  # Year
            df_filtered = df_filtered[pd.to_datetime(df_filtered['boe_approval_date'], utc=True).dt.year.isin(selected_periods)]

    # Apply existing drill-down filters for demurrage
    df_filtered_dem = duration_buckets(df_filtered.copy())
    filter_dem = st.session_state.dem_drilldown_filter
    if filter_dem.get('duration_bucket'):
        df_filtered_dem = df_filtered_dem[df_filtered_dem['duration_bucket'] == filter_dem['duration_bucket']]
    if filter_dem.get('port_of_discharge'):
        df_filtered_dem = df_filtered_dem[df_filtered_dem['port_of_discharge'] == filter_dem['port_of_discharge']]
    if filter_dem.get('terminal'):
        df_filtered_dem = df_filtered_dem[df_filtered_dem['terminal'] == filter_dem['terminal']]
    if filter_dem.get('shipping_line_name'):
        df_filtered_dem = df_filtered_dem[df_filtered_dem['shipping_line_name'] == filter_dem['shipping_line_name']]
    if filter_dem.get('hs4'):
        df_filtered_dem = df_filtered_dem[df_filtered_dem['hs4'] == filter_dem['hs4']]
    if filter_dem.get('importer_label'):
        df_filtered_dem = df_filtered_dem[df_filtered_dem['importer_label'] == filter_dem['importer_label']]
    if filter_dem.get('package_type'):
        df_filtered_dem = df_filtered_dem[df_filtered_dem['package_type'] == filter_dem['package_type']]

    # Apply existing drill-down filters for rent
    df_filtered_rent = duration_buckets(df_filtered.copy())
    filter_rent = st.session_state.rent_drilldown_filter
    if filter_rent.get('duration_bucket'):
        df_filtered_rent = df_filtered_rent[df_filtered_rent['duration_bucket'] == filter_rent['duration_bucket']]
    if filter_rent.get('port_of_discharge'):
        df_filtered_rent = df_filtered_rent[df_filtered_rent['port_of_discharge'] == filter_rent['port_of_discharge']]
    if filter_rent.get('terminal'):
        df_filtered_rent = df_filtered_rent[df_filtered_rent['terminal'] == filter_rent['terminal']]
    if filter_rent.get('shipping_line_name'):
        df_filtered_rent = df_filtered_rent[df_filtered_rent['shipping_line_name'] == filter_rent['shipping_line_name']]
    if filter_rent.get('hs4'):
        df_filtered_rent = df_filtered_rent[df_filtered_rent['hs4'] == filter_rent['hs4']]
    if filter_rent.get('importer_label'):
        df_filtered_rent = df_filtered_rent[df_filtered_rent['importer_label'] == filter_rent['importer_label']]
    if filter_rent.get('package_type'):
        df_filtered_rent = df_filtered_rent[df_filtered_rent['package_type'] == filter_rent['package_type']]

    # --- SUMMARY STRIP (KEY KPIs) ---
    render_summary(summary)

    # --- TOP-LEVEL VIEW MENU (Hydralit nav-bar or fallback) ---
    view_options = ["Demurrage Analysis", "Terminal Rent Analysis", "Raw Records Table"]

    if HYDRALIT_AVAILABLE:
        menu_def = [
            {"label": "Demurrage Analysis", "icon": "bi-cash-coin"},
            {"label": "Terminal Rent Analysis", "icon": "bi-building"},
            {"label": "Raw Records Table", "icon": "bi-table"},
        ]
        nav_theme = {
            "txc_inactive": "#CBD5E1",
            "txc_active": "#FFFFFF",
            "menu_background": "#0F172A",
            "option_active": "#3B82F6",
        }
        active_view = hc.nav_bar(
            menu_definition=menu_def,
            home_name="Demurrage Analysis",
            override_theme=nav_theme,
            hide_streamlit_markers=True,
            sticky_nav=True,
        )
    else:
        active_view = st.radio(
            "Select View",
            options=view_options,
            horizontal=True,
        )

    # ====================== DEMURRAGE VIEW ======================
    if active_view == "Demurrage Analysis":
        col_clear_dem, _ = st.columns([1, 3])
        if col_clear_dem.button("Clear Demurrage Drill-down Filter"):
            st.session_state.dem_drilldown_filter = {}
            st.rerun()

        st.markdown("## Demurrage Analysis")
        
        # Package Type Filter
        col_filter, _ = st.columns([1, 3])
        with col_filter:
            package_filter_enabled = st.checkbox(
                "Enable Package Type Filter",
                key="package_type_filter_enabled",
                value=True,  # Enable by default
                help="When checked, only calculate demurrage based on package type: Containers (0-21 days) and Vehicles in Container (0-60 days)"
            )
        
        total_dem = df_filtered_dem['demurrage_usd'].sum()
        total_boe = df_filtered_dem['boe_no'].nunique()
        avg_dem = total_dem / total_boe if total_boe else 0.0
        
        # Apply package type filter if enabled
        if package_filter_enabled:
            df_filtered_dem = apply_package_type_filter(df_filtered_dem)
            # Recalculate metrics with filtered data
            total_dem = df_filtered_dem['demurrage_usd'].sum()
            total_boe = df_filtered_dem['boe_no'].nunique()
            avg_dem = total_dem / total_boe if total_boe else 0.0
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Total Demurrage (USD)", f"{total_dem:,.2f}")
        c2.metric("Total BOE Records", f"{total_boe}")
        c3.metric("Average Demurrage per BOE (USD)", f"{avg_dem:,.2f}")

        # --- CHART MODE MENU (Hydralit mini-menu or radio buttons) ---
        chart_modes = [
            "Trend Over Time",
            "By Duration Bucket",
            "By Port",
            "By Terminal",
            "By Importer",
            "By Shipping Line",
            "By HS4 Group",
            "By Package Type",
        ]

        if HYDRALIT_AVAILABLE:
            chart_menu_def = [
                {"label": "Trend Over Time", "icon": "bi-graph-up"},
                {"label": "By Duration Bucket", "icon": "bi-hourglass-split"},
                {"label": "By Port", "icon": "bi-geo-alt"},
                {"label": "By Terminal", "icon": "bi-building"},
                {"label": "By Importer", "icon": "bi-person-badge"},
                {"label": "By Shipping Line", "icon": "bi-truck"},
                {"label": "By HS4 Group", "icon": "bi-grid-3x3-gap"},
                {"label": "By Package Type", "icon": "bi-box-seam"},
            ]
            selected_chart_mode = hc.nav_bar(
                menu_definition=chart_menu_def,
                home_name="Trend Over Time",
                override_theme={
                    "txc_inactive": "#64748B",
                    "txc_active": "#0F172A",
                    "menu_background": "#FFFFFF",
                    "option_active": "#E5F0FF",
                },
                hide_streamlit_markers=False,
                sticky_nav=False,
                key="demurrage_chart_menu",
            )
        else:
            selected_chart_mode = st.radio(
                "Chart View",
                options=chart_modes,
                horizontal=True,
            )

        # --- TREND OVER TIME ---
        if selected_chart_mode == "Trend Over Time":
            render_explain_expander(
                (
                    "This chart shows total demurrage cost and average duration over the selected time granularity (Day/Month/Quarter/Year).\n\n"
                    "Use the Time Period Drill-Down above to filter to specific periods."
                ),
                key='dem_trend_ex',
                title='Trend Over Time'
            )
            st.markdown(f"### Trend Over Time ({granularity})")
            if not df_filtered_dem.empty and 'boe_approval_date' in df_filtered_dem.columns:
                df_trend = df_filtered_dem.copy()
                df_trend['date'] = pd.to_datetime(df_trend['boe_approval_date'], utc=True)

                if granularity == 'Day':
                    grouped = df_trend.groupby(df_trend['date'].dt.date).agg(
                        total_value=('demurrage_usd', 'sum'),
                        avg_duration=('duration_days', 'mean')
                    ).reset_index()
                    grouped['date'] = pd.to_datetime(grouped['date'])
                    if not grouped.empty:
                        base = alt.Chart(grouped).encode(x=alt.X('date:T', title='Date'))
                        line_dem = base.mark_line(stroke=LINE_COLORS['primary'], point=True, strokeWidth=3).encode(y='total_value:Q')
                        line_dur = base.mark_line(stroke=LINE_COLORS['secondary'], point=True, strokeWidth=3).encode(y='avg_duration:Q')
                        chart = alt.layer(line_dem, line_dur).resolve_scale(y='independent')
                        safe_altair_chart(chart, height=320)

                elif granularity == 'Month':
                    df_trend['period'] = df_trend['date'].dt.to_period('M').dt.to_timestamp()
                    grouped = df_trend.groupby('period').agg(
                        total_value=('demurrage_usd', 'sum'),
                        avg_duration=('duration_days', 'mean')
                    ).reset_index()
                    if not grouped.empty:
                        base = alt.Chart(grouped).encode(x=alt.X('period:T', title='Month'))
                        line_dem = base.mark_line(stroke=LINE_COLORS['primary'], point=True, strokeWidth=3).encode(y='total_value:Q')
                        line_dur = base.mark_line(stroke=LINE_COLORS['secondary'], point=True, strokeWidth=3).encode(y='avg_duration:Q')
                        chart = alt.layer(line_dem, line_dur).resolve_scale(y='independent')
                        safe_altair_chart(chart, height=320)

                elif granularity == 'Quarter':
                    df_trend['period'] = df_trend['date'].dt.to_period('Q').dt.to_timestamp()
                    grouped = df_trend.groupby('period').agg(
                        total_value=('demurrage_usd', 'sum'),
                        avg_duration=('duration_days', 'mean')
                    ).reset_index()
                    if not grouped.empty:
                        base = alt.Chart(grouped).encode(x=alt.X('period:T', title='Quarter'))
                        line_dem = base.mark_line(stroke=LINE_COLORS['primary'], point=True, strokeWidth=3).encode(y='total_value:Q')
                        line_dur = base.mark_line(stroke=LINE_COLORS['secondary'], point=True, strokeWidth=3).encode(y='avg_duration:Q')
                        chart = alt.layer(line_dem, line_dur).resolve_scale(y='independent')
                        safe_altair_chart(chart, height=320)

                else:  # Year
                    grouped = df_trend.groupby(df_trend['date'].dt.year).agg(
                        total_value=('demurrage_usd', 'sum'),
                        avg_duration=('duration_days', 'mean')
                    ).reset_index(names='year')
                    if not grouped.empty:
                        base = alt.Chart(grouped).encode(x=alt.X('year:O', title='Year'))
                        line_dem = base.mark_line(stroke=LINE_COLORS['primary'], point=True, strokeWidth=3).encode(y='total_value:Q')
                        line_dur = base.mark_line(stroke=LINE_COLORS['secondary'], point=True, strokeWidth=3).encode(y='avg_duration:Q')
                        chart = alt.layer(line_dem, line_dur).resolve_scale(y='independent')
                        safe_altair_chart(chart, height=320)
            
            st.markdown("---")
            st.markdown("### Filtered Records (Demurrage)")
            render_records_table(df_filtered_dem.to_dict(orient='records'), package_filter_enabled)

        # --- BY DURATION BUCKET ---
        if selected_chart_mode == "By Duration Bucket":
            render_explain_expander(
                (
                    "This bar chart groups shipments by how long containers were detained and shows the total demurrage cost for each group.\n\n"
                    "Use the selectbox below to drill down into a specific duration bucket."
                ),
                key='dem_duration_ex',
                title='Duration Breakdown'
            )
            st.markdown("### Demurrage by Duration Bucket")
            df_dur = duration_buckets(df_filtered_dem)
            if not df_dur.empty:
                dur_grp = df_dur.groupby('duration_bucket')['demurrage_usd'].sum().reset_index(name='total_value')
                chart = alt.Chart(dur_grp).mark_bar().encode(
                    x=alt.X('duration_bucket:N', title='Duration Bucket'),
                    y=alt.Y('total_value:Q', title='Total Demurrage (USD)'),
                    color=alt.Color('duration_bucket:N', scale=alt.Scale(range=VIBRANT_COLORS)),
                    tooltip=[alt.Tooltip('total_value', format=',.2f')]
                )
                safe_altair_chart(chart, height=280)
                options = sorted([str(b) for b in dur_grp['duration_bucket'].dropna().unique()])
                current_dur = st.session_state.dem_drilldown_filter.get('duration_bucket')
                selected_dur = st.selectbox(
                    "Select a Duration Bucket to Drill Down:",
                    options=['All'] + options,
                    index=0 if not current_dur else (options.index(current_dur) + 1) if current_dur in options else 0,
                    key="dem_duration_select"
                )
                if selected_dur == 'All':
                    if 'duration_bucket' in st.session_state.dem_drilldown_filter:
                        del st.session_state.dem_drilldown_filter['duration_bucket']
                        st.rerun()
                elif selected_dur != current_dur:
                    st.session_state.dem_drilldown_filter['duration_bucket'] = selected_dur
                    st.rerun()
            
            st.markdown("---")
            st.markdown("### Filtered Records (Demurrage)")
            render_records_table(df_filtered_dem.to_dict(orient='records'), package_filter_enabled)

        # --- BY PORT ---
        if selected_chart_mode == "By Port":
            render_explain_expander(
                (
                    "This donut chart displays the share of total demurrage cost coming from each port of discharge.\n\n"
                    "Use the selectbox below to drill down into a specific port."
                ),
                key='dem_port_ex',
                title='Port Distribution'
            )
            st.markdown("### Demurrage by Port of Discharge")
            port_grp = group_operational(df_filtered_dem, 'demurrage_usd', 'port_of_discharge')
            if not port_grp.empty:
                chart = alt.Chart(port_grp).mark_arc(innerRadius=80).encode(
                    theta='total_value:Q',
                    color=alt.Color('port_of_discharge:N', scale=alt.Scale(range=VIBRANT_COLORS)),
                    tooltip=[alt.Tooltip('total_value', format=',.2f')]
                )
                safe_altair_chart(chart, height=300)
                options = sorted(port_grp['port_of_discharge'].dropna().unique())
                current_port = st.session_state.dem_drilldown_filter.get('port_of_discharge')
                selected_port = st.selectbox(
                    "Select a Port of Discharge to Drill Down:",
                    options=['All'] + options,
                    index=0 if not current_port else (options.index(current_port) + 1) if current_port in options else 0,
                    key="dem_port_select"
                )
                if selected_port == 'All':
                    if 'port_of_discharge' in st.session_state.dem_drilldown_filter:
                        del st.session_state.dem_drilldown_filter['port_of_discharge']
                        st.rerun()
                elif selected_port != current_port:
                    st.session_state.dem_drilldown_filter['port_of_discharge'] = selected_port
                    st.rerun()
            
            st.markdown("---")
            st.markdown("### Filtered Records (Demurrage)")
            render_records_table(df_filtered_dem.to_dict(orient='records'), package_filter_enabled)

        # --- BY TERMINAL ---
        if selected_chart_mode == "By Terminal":
            st.markdown("### Top Terminals by Demurrage")
            term_grp = group_operational(df_filtered_dem, 'demurrage_usd', 'terminal')
            if not term_grp.empty:
                chart = alt.Chart(term_grp).mark_bar().encode(
                    x=alt.X('total_value:Q', title='Total Demurrage (USD)'),
                    y=alt.Y('terminal:N', sort='-x'),
                    color=alt.Color('terminal:N', scale=alt.Scale(range=VIBRANT_COLORS)),
                    tooltip=[alt.Tooltip('total_value', format=',.2f')]
                )
                safe_altair_chart(chart, height=320)
                options = sorted(term_grp['terminal'].dropna().unique())
                current_term = st.session_state.dem_drilldown_filter.get('terminal')
                selected_term = st.selectbox(
                    "Select a Terminal to Drill Down:",
                    options=['All'] + options,
                    index=0 if not current_term else (options.index(current_term) + 1) if current_term in options else 0,
                    key="dem_terminal_select"
                )
                if selected_term == 'All':
                    if 'terminal' in st.session_state.dem_drilldown_filter:
                        del st.session_state.dem_drilldown_filter['terminal']
                        st.rerun()
                elif selected_term != current_term:
                    st.session_state.dem_drilldown_filter['terminal'] = selected_term
                    st.rerun()
            
            st.markdown("---")
            st.markdown("### Filtered Records (Demurrage)")
            render_records_table(df_filtered_dem.to_dict(orient='records'), package_filter_enabled)

        # --- BY IMPORTER ---
        if selected_chart_mode == "By Importer":
            st.markdown("### Importer Efficiency: Average Demurrage per BOE")
            if 'importer_label' in df_filtered_dem.columns:
                imp_eff = df_filtered_dem.groupby('importer_label').agg(
                    total_value=('demurrage_usd', 'sum'),
                    count=('boe_no', 'nunique')
                ).reset_index()
                imp_eff['avg_value'] = imp_eff['total_value'] / imp_eff['count']
                imp_eff = imp_eff.sort_values('avg_value', ascending=False).head(10)
                if not imp_eff.empty:
                    chart = alt.Chart(imp_eff).mark_bar().encode(
                        x=alt.X('avg_value:Q', title='Avg Demurrage per BOE (USD)'),
                        y=alt.Y('importer_label:N', sort='-x'),
                        color=alt.Color('importer_label:N', scale=alt.Scale(range=VIBRANT_COLORS)),
                        tooltip=['importer_label', alt.Tooltip('avg_value', format=',.2f'), 'count']
                    )
                    safe_altair_chart(chart, height=350)
                    options = sorted(imp_eff['importer_label'].dropna().unique())
                    current_imp = st.session_state.dem_drilldown_filter.get('importer_label')
                    selected_imp = st.selectbox(
                        "Select an Importer to Drill Down:",
                        options=['All'] + options,
                        index=0 if not current_imp else (options.index(current_imp) + 1) if current_imp in options else 0,
                        key="dem_importer_select"
                    )
                    if selected_imp == 'All':
                        if 'importer_label' in st.session_state.dem_drilldown_filter:
                            del st.session_state.dem_drilldown_filter['importer_label']
                            st.rerun()
                    elif selected_imp != current_imp:
                        st.session_state.dem_drilldown_filter['importer_label'] = selected_imp
                        st.rerun()
            
            st.markdown("---")
            st.markdown("### Filtered Records (Demurrage)")
            render_records_table(df_filtered_dem.to_dict(orient='records'), package_filter_enabled)

        # --- BY SHIPPING LINE ---
        if selected_chart_mode == "By Shipping Line":
            st.markdown("### Top Shipping Lines by Demurrage")
            sl_grp = group_operational(df_filtered_dem, 'demurrage_usd', 'shipping_line_name')
            if not sl_grp.empty:
                chart = alt.Chart(sl_grp).mark_bar().encode(
                    x=alt.X('total_value:Q', title='Total Demurrage (USD)'),
                    y=alt.Y('shipping_line_name:N', sort='-x'),
                    color=alt.Color('shipping_line_name:N', scale=alt.Scale(range=VIBRANT_COLORS)),
                    tooltip=[alt.Tooltip('total_value', format=',.2f')]
                )
                safe_altair_chart(chart, height=300)
                options = sorted(sl_grp['shipping_line_name'].dropna().unique())
                current_sl = st.session_state.dem_drilldown_filter.get('shipping_line_name')
                selected_sl = st.selectbox(
                    "Select a Shipping Line to Drill Down:",
                    options=['All'] + options,
                    index=0 if not current_sl else (options.index(current_sl) + 1) if current_sl in options else 0,
                    key="dem_sl_select"
                )
                if selected_sl == 'All':
                    if 'shipping_line_name' in st.session_state.dem_drilldown_filter:
                        del st.session_state.dem_drilldown_filter['shipping_line_name']
                        st.rerun()
                elif selected_sl != current_sl:
                    st.session_state.dem_drilldown_filter['shipping_line_name'] = selected_sl
                    st.rerun()
            
            st.markdown("---")
            st.markdown("### Filtered Records (Demurrage)")
            render_records_table(df_filtered_dem.to_dict(orient='records'), package_filter_enabled)

        # --- BY HS4 GROUP ---
        if selected_chart_mode == "By HS4 Group" and 'hs4' in df_filtered_dem.columns:
            st.markdown("### Top HS4 Groups by Demurrage")
            hs_grp = group_operational(df_filtered_dem, 'demurrage_usd', 'hs4')
            if not hs_grp.empty:
                chart = alt.Chart(hs_grp).mark_bar().encode(
                    x=alt.X('total_value:Q', title='Total Demurrage (USD)'),
                    y=alt.Y('hs4:N', sort='-x'),
                    color=alt.Color('hs4:N', scale=alt.Scale(range=VIBRANT_COLORS)),
                    tooltip=[alt.Tooltip('total_value', format=',.2f')]
                )
                safe_altair_chart(chart, height=300)
                options = sorted(hs_grp['hs4'].dropna().unique())
                current_hs = st.session_state.dem_drilldown_filter.get('hs4')
                selected_hs = st.selectbox(
                    "Select an HS4 Group to Drill Down:",
                    options=['All'] + options,
                    index=0 if not current_hs else (options.index(current_hs) + 1) if current_hs in options else 0,
                    key="dem_hs4_select"
                )
                if selected_hs == 'All':
                    if 'hs4' in st.session_state.dem_drilldown_filter:
                        del st.session_state.dem_drilldown_filter['hs4']
                        st.rerun()
                elif selected_hs != current_hs:
                    st.session_state.dem_drilldown_filter['hs4'] = selected_hs
                    st.rerun()
            
            st.markdown("---")
            st.markdown("### Filtered Records (Demurrage)")
            render_records_table(df_filtered_dem.to_dict(orient='records'), package_filter_enabled)

        # --- BY PACKAGE TYPE ---
        if selected_chart_mode == "By Package Type":
            render_explain_expander(
                (
                    "This donut chart displays the share of total demurrage cost coming from each package type.\n\n"
                    "Use the selectbox below to drill down into a specific package type."
                ),
                key='dem_package_ex',
                title='Package Type Distribution'
            )
            st.markdown("### Demurrage by Package Type")
            
            # Show regular package type chart (works like other drill-down sections)
            if 'package_type' in df_filtered_dem.columns:
                pkg_grp = group_operational(df_filtered_dem, 'demurrage_usd', 'package_type')
                if not pkg_grp.empty:
                    chart = alt.Chart(pkg_grp).mark_arc(innerRadius=80).encode(
                        theta='total_value:Q',
                        color=alt.Color('package_type:N', scale=alt.Scale(range=VIBRANT_COLORS)),
                        tooltip=[alt.Tooltip('total_value', format=',.2f')]
                    )
                    safe_altair_chart(chart, height=300)
                    options = sorted(pkg_grp['package_type'].dropna().unique())
                    current_pkg = st.session_state.dem_drilldown_filter.get('package_type')
                    selected_pkg = st.selectbox(
                        "Select a Package Type to Drill Down:",
                        options=['All'] + options,
                        index=0 if not current_pkg else (options.index(current_pkg) + 1) if current_pkg in options else 0,
                        key="dem_package_select"
                    )
                    if selected_pkg == 'All':
                        if 'package_type' in st.session_state.dem_drilldown_filter:
                            del st.session_state.dem_drilldown_filter['package_type']
                            st.rerun()
                    elif selected_pkg != current_pkg:
                        st.session_state.dem_drilldown_filter['package_type'] = selected_pkg
                        st.rerun()
            
            st.markdown("---")
            st.markdown("### Filtered Records (Demurrage)")
            render_records_table(df_filtered_dem.to_dict(orient='records'), package_filter_enabled)

    # ====================== RENT VIEW ======================
    elif active_view == "Terminal Rent Analysis":
        col_clear_rent, _ = st.columns([1, 3])
        if col_clear_rent.button("Clear Rent Drill-down Filter"):
            st.session_state.rent_drilldown_filter = {}
            st.rerun()

        st.markdown("## Terminal Rent Analysis")
        total_rent = df_filtered_rent['total_rent_ghc'].sum()
        rent_details = summary.get('rent_details', {})
        container_rent = rent_details.get('total_container_rent_ghc', 0.0)
        vehicle_rent = rent_details.get('total_vehicle_rent_ghc', 0.0)
        rc1, rc2, rc3 = st.columns(3)
        rc1.metric("Total Rent (GHC)", f"{total_rent:,.2f}")
        rc2.metric("Container Rent (GHC)", f"{container_rent:,.2f}")
        rc3.metric("Vehicle Rent (GHC)", f"{vehicle_rent:,.2f}")

        rent_chart_modes = [
            "Trend Over Time",
            "By Duration Bucket",
            "By Port",
            "By Terminal",
            "By Importer",
            "By Shipping Line",
            "By HS4 Group",
        ]

        if HYDRALIT_AVAILABLE:
            rent_chart_menu_def = [
                {"label": "Trend Over Time", "icon": "bi-graph-up"},
                {"label": "By Duration Bucket", "icon": "bi-hourglass-split"},
                {"label": "By Port", "icon": "bi-geo-alt"},
                {"label": "By Terminal", "icon": "bi-building"},
                {"label": "By Importer", "icon": "bi-person-badge"},
                {"label": "By Shipping Line", "icon": "bi-truck"},
                {"label": "By HS4 Group", "icon": "bi-grid-3x3-gap"},
            ]
            selected_rent_chart_mode = hc.nav_bar(
                menu_definition=rent_chart_menu_def,
                home_name="Trend Over Time",
                override_theme={
                    "txc_inactive": "#64748B",
                    "txc_active": "#0F172A",
                    "menu_background": "#FFFFFF",
                    "option_active": "#E5F0FF",
                },
                hide_streamlit_markers=False,
                sticky_nav=False,
                key="rent_chart_menu",
            )
        else:
            selected_rent_chart_mode = st.radio(
                "Chart View",
                options=rent_chart_modes,
                horizontal=True,
                key="rent_chart_radio"
            )

        # --- TREND OVER TIME ---
        if selected_rent_chart_mode == "Trend Over Time":
            render_explain_expander(
                (
                    "This area chart shows total terminal rent over the selected time granularity, stacked by package type (container vs vehicle).\n\n"
                    "Use the Time Period Drill-Down above to filter to specific periods."
                ),
                key='rent_trend_ex',
                title='Trend Over Time'
            )
            st.markdown(f"### Rent Trend Over Time ({granularity})")
            if not df_filtered_rent.empty and 'boe_approval_date' in df_filtered_rent.columns:
                df_trend_r = df_filtered_rent.copy()
                df_trend_r['date'] = pd.to_datetime(df_trend_r['boe_approval_date'], utc=True)

                if granularity == 'Day':
                    grouped_r = df_trend_r.groupby([df_trend_r['date'].dt.date, 'package_type'])['total_rent_ghc'].sum().reset_index(name='total_value')
                    grouped_r['date'] = pd.to_datetime(grouped_r['date'])
                    x_field = 'date:T'
                elif granularity == 'Month':
                    grouped_r = df_trend_r.groupby([df_trend_r['date'].dt.to_period('M').dt.to_timestamp(), 'package_type'])['total_rent_ghc'].sum().reset_index(name='total_value')
                    x_field = 'date:T'
                elif granularity == 'Quarter':
                    grouped_r = df_trend_r.groupby([df_trend_r['date'].dt.to_period('Q').dt.to_timestamp(), 'package_type'])['total_rent_ghc'].sum().reset_index(name='total_value')
                    x_field = 'date:T'
                else:  # Year
                    grouped_r = df_trend_r.groupby([df_trend_r['date'].dt.year.rename('year'), 'package_type'])['total_rent_ghc'].sum().reset_index(name='total_value')
                    x_field = 'year:O'

                if 'total_value' in grouped_r.columns and not grouped_r.empty:
                    chart = alt.Chart(grouped_r).mark_area(point=True).encode(
                        x=alt.X(x_field, title=granularity),
                        y=alt.Y('total_value:Q', title='Total Rent (GHC)'),
                        color=alt.Color('package_type:N', title='Package Type'),
                        tooltip=['package_type', alt.Tooltip('total_value', format=',.2f')]
                    )
                    safe_altair_chart(chart, height=320)
            
            st.markdown("---")
            st.markdown("### Filtered Records (Terminal Rent)")
            render_records_table(df_filtered_rent.to_dict(orient='records'))

        # --- BY DURATION BUCKET ---
        if selected_rent_chart_mode == "By Duration Bucket":
            render_explain_expander(
                (
                    "This stacked bar chart shows total rent broken down by duration buckets and package type.\n\n"
                    "Use the selectbox below to drill down into a specific duration bucket."
                ),
                key='rent_duration_ex',
                title='Duration Breakdown'
            )
            st.markdown("### Rent by Duration Bucket (Stacked by Package Type)")
            df_dur_rent = duration_buckets(df_filtered_rent)
            if not df_dur_rent.empty:
                dur_grp_rent = df_dur_rent.groupby(['duration_bucket', 'package_type'])['total_rent_ghc'].sum().reset_index(name='total_value')
                chart = alt.Chart(dur_grp_rent).mark_bar().encode(
                    x=alt.X('duration_bucket:N', title='Duration Bucket'),
                    y=alt.Y('total_value:Q', title='Total Rent (GHC)'),
                    color=alt.Color('package_type:N'),
                    tooltip=['duration_bucket', 'package_type', alt.Tooltip('total_value', format=',.2f')]
                )
                safe_altair_chart(chart, height=300)
                options = sorted([str(b) for b in dur_grp_rent['duration_bucket'].dropna().unique()])
                current_dur_rent = st.session_state.rent_drilldown_filter.get('duration_bucket')
                selected_dur_rent = st.selectbox(
                    "Select a Duration Bucket to Drill Down:",
                    options=['All'] + options,
                    index=0 if not current_dur_rent else (options.index(current_dur_rent) + 1) if current_dur_rent in options else 0,
                    key="rent_duration_select"
                )
                if selected_dur_rent == 'All':
                    if 'duration_bucket' in st.session_state.rent_drilldown_filter:
                        del st.session_state.rent_drilldown_filter['duration_bucket']
                        st.rerun()
                elif selected_dur_rent != current_dur_rent:
                    st.session_state.rent_drilldown_filter['duration_bucket'] = selected_dur_rent
                    st.rerun()
            
            st.markdown("---")
            st.markdown("### Filtered Records (Terminal Rent)")
            render_records_table(df_filtered_rent.to_dict(orient='records'))

        # --- BY PORT ---
        if selected_rent_chart_mode == "By Port":
            render_explain_expander(
                (
                    "This stacked bar chart shows rent distribution across ports, separated by package type.\n\n"
                    "Use the selectbox below to drill down into a specific port."
                ),
                key='rent_port_ex',
                title='Port Distribution'
            )
            st.markdown("### Rent Distribution by Port (Stacked by Package Type)")
            if 'port_of_discharge' in df_filtered_rent.columns and 'package_type' in df_filtered_rent.columns:
                port_grp = df_filtered_rent.groupby(['port_of_discharge', 'package_type'])['total_rent_ghc'].sum().reset_index(name='total_value')
                if not port_grp.empty:
                    chart = alt.Chart(port_grp).mark_bar().encode(
                        x=alt.X('port_of_discharge:N', title='Port'),
                        y=alt.Y('total_value:Q', title='Total Rent (GHC)'),
                        color=alt.Color('package_type:N'),
                        tooltip=['port_of_discharge', 'package_type', alt.Tooltip('total_value', format=',.2f')]
                    )
                    safe_altair_chart(chart, height=300)
                    options = sorted(port_grp['port_of_discharge'].dropna().unique())
                    current_port_rent = st.session_state.rent_drilldown_filter.get('port_of_discharge')
                    selected_port_rent = st.selectbox(
                        "Select a Port to Drill Down:",
                        options=['All'] + options,
                        index=0 if not current_port_rent else (options.index(current_port_rent) + 1) if current_port_rent in options else 0,
                        key="rent_port_select"
                    )
                    if selected_port_rent == 'All':
                        if 'port_of_discharge' in st.session_state.rent_drilldown_filter:
                            del st.session_state.rent_drilldown_filter['port_of_discharge']
                            st.rerun()
                    elif selected_port_rent != current_port_rent:
                        st.session_state.rent_drilldown_filter['port_of_discharge'] = selected_port_rent
                        st.rerun()
            
            st.markdown("---")
            st.markdown("### Filtered Records (Terminal Rent)")
            render_records_table(df_filtered_rent.to_dict(orient='records'))

        # --- BY TERMINAL ---
        if selected_rent_chart_mode == "By Terminal":
            render_explain_expander(
                (
                    "This horizontal stacked bar chart ranks terminals by total rent, broken down by package type.\n\n"
                    "Use the selectbox below to drill down into a specific terminal."
                ),
                key='rent_terminal_ex',
                title='Terminal Breakdown'
            )
            st.markdown("### Rent by Terminal (Stacked by Package Type)")
            if 'terminal' in df_filtered_rent.columns and 'package_type' in df_filtered_rent.columns:
                term_grp = df_filtered_rent.groupby(['terminal', 'package_type'])['total_rent_ghc'].sum().reset_index(name='total_value')
                chart = alt.Chart(term_grp).mark_bar().encode(
                    y=alt.Y('terminal:N', sort=alt.EncodingSortField('total_value', order='descending')),
                    x=alt.X('total_value:Q', title='Total Rent (GHC)'),
                    color=alt.Color('package_type:N'),
                    tooltip=['terminal', 'package_type', alt.Tooltip('total_value', format=',.2f')]
                )
                safe_altair_chart(chart, height=350)
                options = sorted(term_grp['terminal'].dropna().unique())
                current_term_rent = st.session_state.rent_drilldown_filter.get('terminal')
                selected_term_rent = st.selectbox(
                    "Select a Terminal to Drill Down:",
                    options=['All'] + options,
                    index=0 if not current_term_rent else (options.index(current_term_rent) + 1) if current_term_rent in options else 0,
                    key="rent_terminal_select"
                )
                if selected_term_rent == 'All':
                    if 'terminal' in st.session_state.rent_drilldown_filter:
                        del st.session_state.rent_drilldown_filter['terminal']
                        st.rerun()
                elif selected_term_rent != current_term_rent:
                    st.session_state.rent_drilldown_filter['terminal'] = selected_term_rent
                    st.rerun()
            
            st.markdown("---")
            st.markdown("### Filtered Records (Terminal Rent)")
            render_records_table(df_filtered_rent.to_dict(orient='records'))

        # --- BY IMPORTER ---
        if selected_rent_chart_mode == "By Importer":
            render_explain_expander(
                (
                    "This chart shows the top 10 importers ranked by average rent per BOE.\n\n"
                    "Use the selectbox below to drill down into a specific importer."
                ),
                key='rent_importer_ex',
                title='Importer Efficiency'
            )
            st.markdown("### Importer Efficiency: Average Rent per BOE")
            if 'importer_label' in df_filtered_rent.columns:
                imp_eff = df_filtered_rent.groupby('importer_label').agg(
                    total_value=('total_rent_ghc', 'sum'),
                    count=('boe_no', 'nunique')
                ).reset_index()
                imp_eff['avg_value'] = imp_eff['total_value'] / imp_eff['count']
                imp_eff = imp_eff.sort_values('avg_value', ascending=False).head(10)
                if not imp_eff.empty:
                    chart = alt.Chart(imp_eff).mark_bar().encode(
                        x=alt.X('avg_value:Q', title='Avg Rent per BOE (GHC)'),
                        y=alt.Y('importer_label:N', sort='-x'),
                        tooltip=['importer_label', alt.Tooltip('avg_value', format=',.2f'), 'count']
                    )
                    safe_altair_chart(chart, height=350)
                    options = sorted(imp_eff['importer_label'].dropna().unique())
                    current_imp_rent = st.session_state.rent_drilldown_filter.get('importer_label')
                    selected_imp_rent = st.selectbox(
                        "Select an Importer to Drill Down:",
                        options=['All'] + options,
                        index=0 if not current_imp_rent else (options.index(current_imp_rent) + 1) if current_imp_rent in options else 0,
                        key="rent_importer_select"
                    )
                    if selected_imp_rent == 'All':
                        if 'importer_label' in st.session_state.rent_drilldown_filter:
                            del st.session_state.rent_drilldown_filter['importer_label']
                            st.rerun()
                    elif selected_imp_rent != current_imp_rent:
                        st.session_state.rent_drilldown_filter['importer_label'] = selected_imp_rent
                        st.rerun()
            
            st.markdown("---")
            st.markdown("### Filtered Records (Terminal Rent)")
            render_records_table(df_filtered_rent.to_dict(orient='records'))

        # --- BY SHIPPING LINE ---
        if selected_rent_chart_mode == "By Shipping Line":
            render_explain_expander(
                (
                    "This horizontal stacked bar chart ranks top shipping lines by total rent, broken down by package type.\n\n"
                    "Use the selectbox below to drill down into a specific shipping line."
                ),
                key='rent_sl_ex',
                title='Shipping Lines Breakdown'
            )
            st.markdown("### Top Shipping Lines by Rent")
            sl_grp = group_operational(df_filtered_rent, 'total_rent_ghc', 'shipping_line_name')
            if not sl_grp.empty and 'package_type' in df_filtered_rent.columns:
                top_sl = sl_grp['shipping_line_name'].tolist()
                sl_pkg = df_filtered_rent[df_filtered_rent['shipping_line_name'].isin(top_sl)].groupby(['shipping_line_name', 'package_type'])['total_rent_ghc'].sum().reset_index(name='total_value')
                if not sl_pkg.empty:
                    chart = alt.Chart(sl_pkg).mark_bar().encode(
                        y=alt.Y('shipping_line_name:N', sort=alt.EncodingSortField('total_value', order='descending')),
                        x=alt.X('total_value:Q', title='Total Rent (GHC)'),
                        color=alt.Color('package_type:N'),
                        tooltip=[alt.Tooltip('total_value', format=',.2f')]
                    )
                    safe_altair_chart(chart, height=300)
                    options = sorted(sl_grp['shipping_line_name'].dropna().unique())
                    current_sl_rent = st.session_state.rent_drilldown_filter.get('shipping_line_name')
                    selected_sl_rent = st.selectbox(
                        "Select a Shipping Line to Drill Down:",
                        options=['All'] + options,
                        index=0 if not current_sl_rent else (options.index(current_sl_rent) + 1) if current_sl_rent in options else 0,
                        key="rent_sl_select"
                    )
                    if selected_sl_rent == 'All':
                        if 'shipping_line_name' in st.session_state.rent_drilldown_filter:
                            del st.session_state.rent_drilldown_filter['shipping_line_name']
                            st.rerun()
                    elif selected_sl_rent != current_sl_rent:
                        st.session_state.rent_drilldown_filter['shipping_line_name'] = selected_sl_rent
                        st.rerun()
            
            st.markdown("---")
            st.markdown("### Filtered Records (Terminal Rent)")
            render_records_table(df_filtered_rent.to_dict(orient='records'))

        # --- BY HS4 GROUP ---
        if selected_rent_chart_mode == "By HS4 Group" and 'hs4' in df_filtered_rent.columns:
            render_explain_expander(
                (
                    "This horizontal stacked bar chart ranks top HS4 groups by total rent, broken down by package type.\n\n"
                    "Use the selectbox below to drill down into a specific HS4 group."
                ),
                key='rent_hs4_ex',
                title='HS4 Groups Breakdown'
            )
            st.markdown("### Top HS4 Groups by Rent")
            hs_grp = group_operational(df_filtered_rent, 'total_rent_ghc', 'hs4')
            if not hs_grp.empty and 'package_type' in df_filtered_rent.columns:
                top_hs = hs_grp['hs4'].tolist()
                hs_pkg = df_filtered_rent[df_filtered_rent['hs4'].isin(top_hs)].groupby(['hs4', 'package_type'])['total_rent_ghc'].sum().reset_index(name='total_value')
                if not hs_pkg.empty:
                    chart = alt.Chart(hs_pkg).mark_bar().encode(
                        y=alt.Y('hs4:N', sort=alt.EncodingSortField('total_value', order='descending')),
                        x=alt.X('total_value:Q', title='Total Rent (GHC)'),
                        color=alt.Color('package_type:N'),
                        tooltip=[alt.Tooltip('total_value', format=',.2f')]
                    )
                    safe_altair_chart(chart, height=300)
                    options = sorted(hs_grp['hs4'].dropna().unique())
                    current_hs_rent = st.session_state.rent_drilldown_filter.get('hs4')
                    selected_hs_rent = st.selectbox(
                        "Select an HS4 Group to Drill Down:",
                        options=['All'] + options,
                        index=0 if not current_hs_rent else (options.index(current_hs_rent) + 1) if current_hs_rent in options else 0,
                        key="rent_hs4_select"
                    )
                    if selected_hs_rent == 'All':
                        if 'hs4' in st.session_state.rent_drilldown_filter:
                            del st.session_state.rent_drilldown_filter['hs4']
                            st.rerun()
                    elif selected_hs_rent != current_hs_rent:
                        st.session_state.rent_drilldown_filter['hs4'] = selected_hs_rent
                        st.rerun()
            
            st.markdown("---")
            st.markdown("### Filtered Records (Terminal Rent)")
            render_records_table(df_filtered_rent.to_dict(orient='records'))

    # ====================== RAW TABLE VIEW ======================
    elif active_view == "Raw Records Table":
        st.markdown("## Raw Demurrage & Rent Records")
        st.info("This table shows the FULL unfiltered dataset (all records from your search, before any drill-down filters).")
        render_records_table(df_raw.to_dict(orient='records'))


# Page access control (must match top-of-page auth: is_authenticated())
if is_authenticated():
    try:
        inject_expander_css()
        demurrage_page()
        # Memory cleanup at end of each page load
        gc.collect()
    except Exception as e:
        st.error(f"💥 Page error: {e}")
        st.error("Please refresh the page and try again.")
        st.text(traceback.format_exc())
else:
    st.error('Please log in on the Home page to access the reports.')

