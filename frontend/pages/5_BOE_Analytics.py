"""
BOE Header Analytics: analyse boe_header data with summary, time series, top dimensions, and charts.
All metrics and charts use the FULL dataset in the selected date range; only the sample table is limited.
"""
import os
import sys
import datetime
import streamlit as st
import requests
import pandas as pd
import altair as alt
from pathlib import Path
from typing import Dict, Any, Optional, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.auth_api import get_cookie_manager, restore_from_cookie, is_authenticated

# Auth
cookies = get_cookie_manager()
if not cookies.ready():
    st.stop()
if not is_authenticated():
    restore_from_cookie(cookies)
if not is_authenticated():
    st.warning("Please sign in on the Home page to access the reports.")
    st.page_link("Home.py", label="Go to Sign in", icon="🏠")
    st.stop()

_API_BASE = os.environ.get("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
ANALYTICS_ENDPOINT = f"{_API_BASE}/reports/boe-header-analytics"
DIMENSION_ENDPOINT = f"{_API_BASE}/reports/boe-header-analytics/dimension"
FILTER_OPTIONS_ENDPOINT = f"{_API_BASE}/reports/boe-header-analytics/filter-options"
HSCODE_SUGGEST = f"{_API_BASE}/hscodes/suggestions"
VESSEL_SUGGEST = f"{_API_BASE}/reports/boe-header-suggestions/vessel"
IMPORTER_SUGGEST = f"{_API_BASE}/reports/boe-header-suggestions/importer"

FREQUENCY_KEY = """
| Frequency | Meaning (avg days between BOEs) |
|-----------|----------------------------------|
| **Single shipment** | One BOE only |
| **Weekly or more** | ≤ 7 days |
| **Fortnightly to monthly** | 8–21 days |
| **Monthly** | 22–60 days |
| **Quarterly** | 61–120 days |
| **Yearly** | 121–365 days |
| **Less than yearly** | > 365 days |
"""
DIM_VIEW_MORE_THRESHOLD = 10
PAGE_SIZE_OPTIONS = [50, 100, 200, 500, 1000]
DEFAULT_PAGE_SIZE = 100

COLORS = ["#1E3A8A", "#FFD700", "#2563EB", "#F59E0B", "#3B82F6", "#EF4444", "#10B981", "#8B5CF6", "#EC4899", "#06B6D4"]

# Chart colors per dimension (for header + View more link)
DIMENSION_COLORS = {
    "importers": "#2563EB",
    "ports_loading": "#0EA5E9",
    "ports_discharge": "#10B981",
    "shipping_lines": "#F59E0B",
    "hs_codes": "#8B5CF6",
    "cargo_type": COLORS[0],
    "package_type": "#06B6D4",
}
DIMENSION_TITLES = {
    "importers": "Top importers",
    "ports_loading": "Top ports of loading",
    "ports_discharge": "Top ports of discharge",
    "shipping_lines": "Top shipping lines",
    "hs_codes": "Top HS codes (4-digit)",
    "cargo_type": "Cargo type",
    "package_type": "Package type",
}
DIMENSION_COLUMNS = {
    "importers": ["importer_name", "importer_tin", "boe_count", "item_count", "net_weight", "avg_days_between", "frequency"],
    "ports_loading": ["port", "count", "net_weight"],
    "ports_discharge": ["port", "count", "net_weight"],
    "shipping_lines": ["name", "count", "net_weight"],
    "hs_codes": ["hs_code", "count", "net_weight"],
    "cargo_type": ["name", "count", "net_weight"],
    "package_type": ["name", "count", "net_weight"],
}
DIMENSION_DESCRIPTIONS = {
    "importers": "Aggregated list of importers with BOE count, item count, net weight, average days between BOEs, and shipment frequency (e.g. Monthly, Quarterly) for the selected filters.",
    "ports_loading": "Ports of loading with item count and total net weight for the selected filters.",
    "ports_discharge": "Ports of discharge with item count and total net weight for the selected filters.",
    "shipping_lines": "Shipping lines with item count and total net weight for the selected filters.",
    "hs_codes": "4-digit HS codes with item count and total net weight for the selected filters.",
    "cargo_type": "Cargo types with item count and total net weight for the selected filters.",
    "package_type": "Package types with item count and total net weight for the selected filters.",
}


def fetch_analytics(params: Dict[str, Any]):
    try:
        flat_params = []
        for k, v in params.items():
            if isinstance(v, list):
                for item in v:
                    flat_params.append((k, item))
            else:
                flat_params.append((k, v))
        resp = requests.get(ANALYTICS_ENDPOINT, params=flat_params, timeout=120)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        st.error(f"API request failed: {e}")
        return None


def build_analytics_params(offset: int = 0, page_size: int = 500) -> Dict[str, Any]:
    """Build analytics request params from current session state (for Run report and pagination)."""
    params = {
        "start_date": str(st.session_state.get("boe_analytics_start", "")),
        "end_date": str(st.session_state.get("boe_analytics_end", "")),
        "limit_records": page_size,
        "offset": offset,
    }
    vessel_names = st.session_state.get("boe_selected_vessels") or []
    if vessel_names:
        params["vessel_name_keywords"] = vessel_names
    if st.session_state.get("boe_boe_no", "").strip():
        params["boe_no"] = st.session_state["boe_boe_no"].strip()
    if st.session_state.get("boe_bl_number", "").strip():
        params["bl_number"] = st.session_state["boe_bl_number"].strip()
    if st.session_state.get("boe_importer_tin", "").strip():
        params["importer_tin"] = st.session_state["boe_importer_tin"].strip()
    selected_importers = st.session_state.get("boe_selected_importers") or []
    tins = [x.get("tin") for x in selected_importers if x.get("tin")]
    if tins and not params.get("importer_tin"):
        params["importer_tins"] = tins
    if st.session_state.get("boe_item_desc", "").strip():
        params["item_description_keywords"] = st.session_state["boe_item_desc"].strip()
    if st.session_state.get("boe_hs_prefix", "").strip():
        params["hs_code_prefix"] = st.session_state["boe_hs_prefix"].strip()
    pkg = st.session_state.get("boe_selected_package_types") or []
    if pkg:
        params["package_types"] = pkg
    cargo = st.session_state.get("boe_selected_cargo_types") or []
    if cargo:
        params["cargo_types"] = cargo
    ports_d = st.session_state.get("boe_selected_ports_discharge") or []
    if ports_d:
        params["ports_discharge"] = ports_d
    pol = st.session_state.get("boe_selected_ports_loading") or []
    if pol:
        params["port_of_loading_keywords"] = pol
    return params


def _dimension_params(offset: int = 0, limit: int = DEFAULT_PAGE_SIZE) -> List[tuple]:
    """Params for dimension endpoint (same filters as analytics, plus dim, offset, limit)."""
    base = build_analytics_params(offset=0, page_size=500)
    base.pop("limit_records", None)
    base.pop("offset", None)
    base["offset"] = offset
    base["limit"] = limit
    flat = []
    for k, v in base.items():
        if isinstance(v, list):
            for i in v:
                flat.append((k, i))
        else:
            flat.append((k, v))
    return flat


def fetch_dimension(dim: str, offset: int = 0, limit: int = DEFAULT_PAGE_SIZE) -> Optional[Dict[str, Any]]:
    """Fetch paginated dimension data for View more dialog."""
    try:
        params = _dimension_params(offset=offset, limit=limit)
        params.append(("dim", dim))
        resp = requests.get(DIMENSION_ENDPOINT, params=params, timeout=60)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException:
        return None


DIM_FETCH_PAGE_SIZE = 2000  # API max for dimension endpoint


def fetch_dimension_all(dim: str, columns: List[str]) -> Optional[pd.DataFrame]:
    """Fetch all dimension rows by paging (limit 2000 per request). Returns DataFrame or None."""
    all_items: List[Dict[str, Any]] = []
    offset = 0
    while True:
        data = fetch_dimension(dim, offset=offset, limit=DIM_FETCH_PAGE_SIZE)
        if not data:
            return None
        items = data.get("items") or []
        if not items:
            break
        all_items.extend(items)
        if len(items) < DIM_FETCH_PAGE_SIZE:
            break
        offset += DIM_FETCH_PAGE_SIZE
    if not all_items:
        return pd.DataFrame()
    df = pd.DataFrame(all_items)
    display_cols = [c for c in columns if c in df.columns] or list(df.columns)
    return df[display_cols]


def get_dimension_total(dim: str) -> int:
    """Return total row count for dimension (lightweight: fetches one row)."""
    data = fetch_dimension(dim, offset=0, limit=1)
    return (data or {}).get("total", 0)


def _dimension_dialog_on_dismiss():
    st.session_state.pop("boe_dim_view_more", None)


@st.dialog(
    " ",  # Title bar minimal; real title is big heading inside
    width="large",
    dismissible=True,
    on_dismiss=_dimension_dialog_on_dismiss,
)
def dimension_view_dialog(dim: str) -> None:
    """Modal with paginated table and records-per-page selector."""
    title = DIMENSION_TITLES.get(dim, dim)
    columns = DIMENSION_COLUMNS.get(dim, [])
    page_key = f"boe_dim_page_{dim}"
    page_size = st.session_state.get("boe_dim_page_size", DEFAULT_PAGE_SIZE)
    if page_size not in PAGE_SIZE_OPTIONS:
        page_size = DEFAULT_PAGE_SIZE
    last_ps = st.session_state.get("boe_dim_last_ps")
    if last_ps is not None and last_ps != page_size:
        st.session_state[page_key] = 1
        st.session_state["boe_dim_last_ps"] = page_size
    st.session_state["boe_dim_last_ps"] = page_size
    if page_key not in st.session_state:
        st.session_state[page_key] = 1
    page = st.session_state[page_key]
    offset = (page - 1) * page_size
    data = fetch_dimension(dim, offset=offset, limit=page_size)
    if not data:
        st.warning("Could not load dimension data.")
        if st.button("Close", key="dim_dialog_close"):
            _dimension_dialog_on_dismiss()
            st.rerun()
        return
    items = data.get("items") or []
    total = data.get("total") or 0
    total_pages = max(1, (total + page_size - 1) // page_size)
    st.markdown(f"# {title} — {total:,} rows")
    desc = DIMENSION_DESCRIPTIONS.get(dim, "Aggregated dimension data for the selected filters.")
    st.caption(desc)
    if not items:
        st.info("No rows for this dimension with current filters.")
        if st.button("Close", key="dim_dialog_close"):
            _dimension_dialog_on_dismiss()
            st.rerun()
        return
    # Top of table: Records per page + Download CSV + Close
    rpp_col, dl_col, close_col = st.columns([2, 2, 1])
    with rpp_col:
        st.selectbox(
            "Records per page",
            options=PAGE_SIZE_OPTIONS,
            index=PAGE_SIZE_OPTIONS.index(page_size) if page_size in PAGE_SIZE_OPTIONS else 1,
            key="boe_dim_page_size",
            format_func=lambda x: f"{x} records",
        )
    with dl_col:
        full = fetch_dimension(dim, offset=0, limit=10000)
        if full and full.get("items"):
            out_df = pd.DataFrame(full["items"])
            out_cols = [c for c in columns if c in out_df.columns] or list(out_df.columns)
            csv = out_df[out_cols].to_csv(index=False)
            st.download_button("Download CSV", data=csv, file_name=f"boe_{dim}.csv", mime="text/csv", key=f"dim_dl_{dim}")
        if st.button("Prepare full data download", key=f"dim_prepare_full_{dim}"):
            with st.spinner("Fetching all dimension data…"):
                full_df = fetch_dimension_all(dim, columns)
            if full_df is not None and not full_df.empty:
                st.session_state[f"boe_dim_full_csv_{dim}"] = full_df.to_csv(index=False)
                st.rerun()
        if st.session_state.get(f"boe_dim_full_csv_{dim}"):
            st.download_button("Download full data (CSV)", data=st.session_state[f"boe_dim_full_csv_{dim}"], file_name=f"boe_{dim}_full.csv", mime="text/csv", key=f"dim_dl_full_{dim}")
    with close_col:
        if st.button("Close", key="dim_dialog_close"):
            _dimension_dialog_on_dismiss()
            st.rerun()
    df = pd.DataFrame(items)
    display_cols = [c for c in columns if c in df.columns] or list(df.columns)
    st.dataframe(df[display_cols], use_container_width=True, height=min(450, 50 + len(items) * 35))
    # Pagination below table
    info_col, prev_col, next_col = st.columns([2, 1, 1])
    with info_col:
        st.caption(f"Page {page} of {total_pages} ({total:,} total rows)")
    with prev_col:
        if st.button("⬅️ Prev", key=f"dim_prev_{dim}", disabled=(page <= 1), use_container_width=True):
            st.session_state[page_key] = page - 1
            st.rerun()
    with next_col:
        if st.button("Next ➡️", key=f"dim_next_{dim}", disabled=(page >= total_pages), use_container_width=True):
            st.session_state[page_key] = page + 1
            st.rerun()


def fetch_filter_options(start_date: Any, end_date: Any) -> Optional[Dict[str, List[str]]]:
    """Fetch package_types, cargo_types, ports_discharge for the date range (to populate dropdowns)."""
    if not start_date or not end_date:
        return None
    try:
        resp = requests.get(FILTER_OPTIONS_ENDPOINT, params={"start_date": str(start_date), "end_date": str(end_date)}, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException:
        return None


def fetch_suggestions(endpoint: str, param_key: str, param_value: str, min_len: int) -> List[Dict]:
    if len(param_value.strip()) < min_len:
        return []
    try:
        if "hscodes" in endpoint:
            r = requests.get(f"{endpoint}?prefix={param_value.strip()}", timeout=10)
        else:
            r = requests.get(f"{endpoint}?keyword={param_value.strip()}", timeout=10)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.RequestException:
        return []


def main():
    st.title("BOE Header Analytics")
    st.markdown("Analyse Bill of Entry header data. **All charts and metrics use the full dataset** in your date range; only the table at the bottom is a sample for display.")

    now = datetime.datetime.now()
    default_start = (now - datetime.timedelta(days=90)).date()
    default_end = now.date()

    # Defaults for filter fields (same pattern as Demurrage)
    boe_init_defaults = {
        "boe_analytics_start": default_start,
        "boe_analytics_end": default_end,
        "boe_boe_no": "",
        "boe_bl_number": "",
        "boe_importer_tin": "",
        "boe_hs_prefix": "",
        "boe_item_desc": "",
        "boe_vessel_search": "",
        "boe_importer_search": "",
        "boe_vessel_suggestions": [],
        "boe_importer_suggestions": [],
        "boe_selected_vessels": [],
        "boe_selected_importers": [],
        "boe_filter_options": None,
        "boe_selected_package_types": [],
        "boe_selected_cargo_types": [],
        "boe_selected_ports_discharge": [],
        "boe_port_loading_filter": "",
        "boe_selected_ports_loading": [],
        "boe_table_page": 1,
        "boe_records_page_size": DEFAULT_PAGE_SIZE,
        "boe_dim_page_size": DEFAULT_PAGE_SIZE,
    }
    # Set defaults only for non-widget keys so we don't conflict with date_input (avoids Session State API warning)
    widget_keys_skip_init = ("boe_analytics_start", "boe_analytics_end")
    for key, default in boe_init_defaults.items():
        if key in widget_keys_skip_init:
            continue
        if key not in st.session_state:
            st.session_state[key] = default

    # Clear filter (like Demurrage): reset all filter fields and remove results
    if st.session_state.get("boe_clear_widgets_flag", False):
        for key, default in boe_init_defaults.items():
            st.session_state[key] = default
        if "boe_analytics_data" in st.session_state:
            del st.session_state["boe_analytics_data"]
        st.session_state.pop("boe_export_csv", None)
        st.session_state["boe_clear_widgets_flag"] = False
        st.rerun()

    with st.expander("🔍 Filters", expanded=True):
        st.markdown("### Date range (required)")
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input("Start date (BOE approval)", value=st.session_state.get("boe_analytics_start", default_start), key="boe_analytics_start")
        with col2:
            end_date = st.date_input("End date (BOE approval)", value=st.session_state.get("boe_analytics_end", default_end), key="boe_analytics_end")

        if start_date and end_date:
            current_range = (str(start_date), str(end_date))
            if st.session_state.get("boe_filter_options_range") != current_range or st.session_state.get("boe_filter_options") is None:
                opts = fetch_filter_options(start_date, end_date)
                if opts is not None:
                    st.session_state["boe_filter_options"] = opts
                    st.session_state["boe_filter_options_range"] = current_range
        else:
            st.session_state["boe_filter_options"] = None
            st.session_state["boe_filter_options_range"] = None

        st.markdown("### Document & importer (exact or search)")
        tab_doc, tab_hs_item, tab_vessel, tab_importer, tab_ports = st.tabs(["Document numbers", "HS Code & item description", "Search by vessel name", "Importer", "Package, Cargo & Ports"])
        boe_no = ""
        bl_number = ""
        importer_tin = ""
        importer_name_kw = ""
        item_desc_kw = ""
        hs_code_prefix = ""

        with tab_doc:
            boe_no = st.text_input("BOE number (exact)", key="boe_boe_no", placeholder="Optional")
            bl_number = st.text_input("BL number (exact)", key="boe_bl_number", placeholder="Optional")
            importer_tin = st.text_input("Importer TIN (exact)", key="boe_importer_tin", placeholder="Optional")
        with tab_hs_item:
            hs_code_prefix = st.text_input("HS code prefix (e.g. 8703)", key="boe_hs_prefix", placeholder="4+ characters")
            item_desc_kw = st.text_input("Item description (keywords)", key="boe_item_desc", placeholder="Partial match")
        with tab_vessel:
            vessel_search = st.text_input("Search by vessel name", key="boe_vessel_search", placeholder="Type to see suggestions (min 3 characters)")
            if vessel_search.strip() and len(vessel_search.strip()) >= 3:
                sugs = fetch_suggestions(VESSEL_SUGGEST, "keyword", vessel_search, 3)
                st.session_state["boe_vessel_suggestions"] = sugs[:12]
            suggestions = st.session_state.get("boe_vessel_suggestions") or []
            if suggestions:
                st.markdown("**Suggestions (select to add):**")
                col_sugg = st.columns(3)
                for idx, item in enumerate(suggestions):
                    name = item.get("name") or ""
                    if not name:
                        continue
                    is_selected = name in st.session_state["boe_selected_vessels"]
                    with col_sugg[idx % 3]:
                        key_name = f"boe_vessel_suggest_{idx}_{hash(name) % 10**6}"
                        checked = st.checkbox(name[:50] + ("…" if len(name) > 50 else ""), value=is_selected, key=key_name)
                        if checked and not is_selected:
                            st.session_state["boe_selected_vessels"].append(name)
                            st.rerun()
                        if not checked and is_selected:
                            try:
                                st.session_state["boe_selected_vessels"].remove(name)
                            except ValueError:
                                pass
                            st.rerun()
        with tab_importer:
            importer_search = st.text_input("Search importer by name", key="boe_importer_search", placeholder="Type to see suggestions (min 3 characters)")
            if importer_search.strip() and len(importer_search.strip()) >= 3:
                sugs = fetch_suggestions(IMPORTER_SUGGEST, "keyword", importer_search, 3)
                st.session_state["boe_importer_suggestions"] = sugs[:12]
            imp_suggestions = st.session_state.get("boe_importer_suggestions") or []
            if imp_suggestions:
                st.markdown("**Suggestions (select to add):**")
                col_imp = st.columns(3)
                for idx, item in enumerate(imp_suggestions):
                    name = item.get("name") or ""
                    tin = item.get("importerTin") or item.get("tin") or ""
                    if not name:
                        continue
                    label = f"{name} ({tin})" if tin else name
                    existing_tins = [x.get("tin") for x in st.session_state.get("boe_selected_importers", [])]
                    is_selected = tin in existing_tins if tin else (name in [x.get("name") for x in st.session_state.get("boe_selected_importers", [])])
                    with col_imp[idx % 3]:
                        key_name = f"boe_imp_suggest_{idx}_{hash((name, tin)) % 10**6}"
                        checked = st.checkbox(label[:45] + ("…" if len(label) > 45 else ""), value=is_selected, key=key_name)
                        if checked and not is_selected:
                            st.session_state["boe_selected_importers"].append({"name": name, "tin": tin or ""})
                            st.rerun()
                        if not checked and is_selected:
                            st.session_state["boe_selected_importers"] = [x for x in st.session_state["boe_selected_importers"] if not (x.get("tin") == tin and x.get("name") == name)]
                            st.rerun()

        with tab_ports:
            opts = st.session_state.get("boe_filter_options") or {}
            if not opts and start_date and end_date:
                st.caption("Select a date range above; dropdowns will populate.")
            pkg_options = opts.get("package_types") or []
            cargo_options = opts.get("cargo_types") or []
            ports_d_options = opts.get("ports_discharge") or []
            # Use key= so Streamlit stores selection in session state (avoids sync/duplicate-select bugs)
            if "boe_selected_package_types" not in st.session_state:
                st.session_state["boe_selected_package_types"] = []
            if "boe_selected_cargo_types" not in st.session_state:
                st.session_state["boe_selected_cargo_types"] = []
            if "boe_selected_ports_discharge" not in st.session_state:
                st.session_state["boe_selected_ports_discharge"] = []
            st.multiselect("Package type", options=pkg_options, key="boe_selected_package_types")
            st.multiselect("Cargo type", options=cargo_options, key="boe_selected_cargo_types")
            st.multiselect("Port of discharge", options=ports_d_options, key="boe_selected_ports_discharge")
            # Port of loading: dropdown with search (filter text narrows the list in the multiselect)
            ports_loading_options = opts.get("ports_loading") or []
            if "boe_selected_ports_loading" not in st.session_state:
                st.session_state["boe_selected_ports_loading"] = []
            st.text_input("Search in port of loading list", key="boe_port_loading_filter", placeholder="Type to filter the list below…")
            pol_filter = (st.session_state.get("boe_port_loading_filter") or "").strip().lower()
            if pol_filter:
                ports_loading_options = [p for p in ports_loading_options if pol_filter in (p or "").lower()]
            # Keep selected ports in the options so they remain visible when filter is applied
            selected_pol = st.session_state.get("boe_selected_ports_loading") or []
            options_with_selected = sorted(set(ports_loading_options) | set(selected_pol))
            st.multiselect("Port of loading", options=options_with_selected, key="boe_selected_ports_loading")

    col_run, col_clear = st.columns(2)
    with col_run:
        run_clicked = st.button("Run report", type="primary", key="boe_run")
    with col_clear:
        if st.button("Clear filter", key="boe_clear_results"):
            st.session_state["boe_clear_widgets_flag"] = True
            st.rerun()

    page_size = st.session_state.get("boe_records_page_size", DEFAULT_PAGE_SIZE)
    if page_size not in PAGE_SIZE_OPTIONS:
        page_size = DEFAULT_PAGE_SIZE
        st.session_state["boe_records_page_size"] = page_size
    if run_clicked:
        st.session_state["boe_table_page"] = 1
        st.session_state.pop("boe_export_csv", None)
        params = build_analytics_params(offset=0, page_size=page_size)
        with st.spinner("Loading analytics…"):
            data = fetch_analytics(params)
        if data:
            st.session_state["boe_analytics_data"] = data
            st.session_state["boe_last_limit_records"] = page_size
            st.rerun()

    data = st.session_state.get("boe_analytics_data")
    if not data:
        st.info("Set filters and click **Run report**.")
        return

    # Label showing active search filters (Clear is next to Run report; does not clear fields/suggestions)
    d_start = st.session_state.get("boe_analytics_start")
    d_end = st.session_state.get("boe_analytics_end")
    filter_parts = [f"**Date:** {str(d_start) if d_start else ''} → {str(d_end) if d_end else ''}"]
    if st.session_state.get("boe_selected_vessels"):
        filter_parts.append(f"**Vessel(s):** {', '.join(st.session_state['boe_selected_vessels'][:5])}" + (" …" if len(st.session_state["boe_selected_vessels"]) > 5 else ""))
    if st.session_state.get("boe_boe_no"):
        filter_parts.append(f"**BOE:** {st.session_state['boe_boe_no']}")
    if st.session_state.get("boe_bl_number"):
        filter_parts.append(f"**BL:** {st.session_state['boe_bl_number']}")
    if st.session_state.get("boe_importer_tin"):
        filter_parts.append(f"**TIN:** {st.session_state['boe_importer_tin']}")
    if st.session_state.get("boe_selected_importers"):
        names = [x.get("name", "")[:25] for x in st.session_state["boe_selected_importers"][:3]]
        filter_parts.append(f"**Importer(s):** {', '.join(names)}" + (" …" if len(st.session_state["boe_selected_importers"]) > 3 else ""))
    if st.session_state.get("boe_item_desc"):
        filter_parts.append(f"**Item:** {st.session_state['boe_item_desc']}")
    if st.session_state.get("boe_hs_prefix"):
        filter_parts.append(f"**HS:** {st.session_state['boe_hs_prefix']}")
    if st.session_state.get("boe_selected_package_types"):
        p = st.session_state["boe_selected_package_types"][:3]
        filter_parts.append(f"**Package:** {', '.join(p)}" + (" …" if len(st.session_state["boe_selected_package_types"]) > 3 else ""))
    if st.session_state.get("boe_selected_cargo_types"):
        c = st.session_state["boe_selected_cargo_types"][:3]
        filter_parts.append(f"**Cargo:** {', '.join(c)}" + (" …" if len(st.session_state["boe_selected_cargo_types"]) > 3 else ""))
    if st.session_state.get("boe_selected_ports_discharge"):
        pd_ = st.session_state["boe_selected_ports_discharge"][:3]
        filter_parts.append(f"**Port (disch.):** {', '.join(pd_)}" + (" …" if len(st.session_state["boe_selected_ports_discharge"]) > 3 else ""))
    if st.session_state.get("boe_selected_ports_loading"):
        pl_ = st.session_state["boe_selected_ports_loading"][:3]
        filter_parts.append(f"**Port (load):** {', '.join(pl_)}" + (" …" if len(st.session_state["boe_selected_ports_loading"]) > 3 else ""))
    st.markdown("---")
    st.markdown("**Search filters:** " + " | ".join(filter_parts))
    st.markdown("---")

    summary = data.get("summary", {})
    total_unique_boe = summary.get("total_unique_boe", 0)
    total_items = summary.get("total_items", 0)
    total_net = summary.get("total_net_weight", 0)
    total_gross = summary.get("total_gross_weight", 0)

    st.markdown("### Summary (full dataset in range)")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("No. of BOEs", f"{total_unique_boe:,}")
    m2.metric("Total items (lines)", f"{total_items:,}")
    m3.metric("Total net weight", f"{total_net:,.0f}")
    m4.metric("Total gross weight", f"{total_gross:,.0f}")

    if total_items == 0:
        st.warning("No records in the selected range.")
        return

    time_series = data.get("time_series", [])
    top_importers = data.get("top_importers", [])
    top_shipping_lines = data.get("top_shipping_lines", [])
    top_ports_discharge = data.get("top_ports_discharge", [])
    top_ports_loading = data.get("top_ports_loading", [])
    top_hs_codes = data.get("top_hs_codes", [])
    cargo_breakdown = data.get("cargo_type_breakdown", [])
    package_breakdown = data.get("package_type_breakdown", [])

    if time_series:
        st.markdown("### Volume over time (by month)")
        df_ts = pd.DataFrame(time_series)
        df_ts["period"] = pd.to_datetime(df_ts["period"])
        base = alt.Chart(df_ts).encode(x=alt.X("period:T", title="Month"))
        line_boe = base.mark_line(stroke="#1E3A8A", point=True, strokeWidth=3).encode(
            y=alt.Y("unique_boe_count:Q", title="No. of BOEs"),
        )
        line_net = base.mark_line(stroke="#10B981", point=True, strokeWidth=3).encode(
            y=alt.Y("net_weight:Q", title="Total net weight"),
        )
        chart_ts = alt.layer(line_boe, line_net).resolve_scale(y="independent")
        st.altair_chart(chart_ts.properties(height=320), use_container_width=True)

    st.markdown("### Top dimensions (by net weight)")
    # Style View more buttons as hyperlinks (only secondary buttons on this page are View more)
    st.markdown("""
    <style>
    button[kind="secondary"] { background: transparent !important; border: none !important; color: #1f77b4 !important; text-decoration: underline !important; box-shadow: none !important; }
    button[kind="secondary"]:hover { color: #0d5a9e !important; }
    </style>
    """, unsafe_allow_html=True)

    def _dim_header(dim: str, subtitle: str = "") -> None:
        """Render dimension header with chart color and optional View more link (only if total > 10)."""
        color = DIMENSION_COLORS.get(dim, "#333")
        title = DIMENSION_TITLES.get(dim, dim)
        total = get_dimension_total(dim)
        head_col, link_col = st.columns([5, 1])
        with head_col:
            if subtitle:
                st.markdown(f'<span style="color: {color}; font-weight: 700;">{title}</span> <span style="color: #666;">{subtitle}</span>', unsafe_allow_html=True)
            else:
                st.markdown(f'<span style="color: {color}; font-weight: 700;">{title}</span>', unsafe_allow_html=True)
        with link_col:
            if total > DIM_VIEW_MORE_THRESHOLD:
                if st.button("📋", key=f"view_more_{dim}", type="secondary", help="View more"):
                    st.session_state["boe_dim_view_more"] = dim
                    st.rerun()

    if top_importers:
        _dim_header("importers", "(BOEs, items, avg days between, frequency)")
        df_imp = pd.DataFrame(top_importers)
        def _imp_label(row):
            name = (row.get("importer_name") or "")[:30]
            if len((row.get("importer_name") or "")) > 30:
                name += "…"
            boe = row.get("boe_count", 0)
            items = row.get("item_count", 0)
            avg = row.get("avg_days_between")
            freq = row.get("frequency") or ""
            if avg is not None:
                return f"{name} ({boe} BOEs, {items} items, ~{avg}d, {freq})"
            return f"{name} ({boe} BOEs, {items} items, {freq})"
        df_imp["label"] = df_imp.apply(_imp_label, axis=1)
        chart_imp = alt.Chart(df_imp).mark_bar(color="#2563EB").encode(
            x=alt.X("net_weight:Q", title="Net weight"),
            y=alt.Y("label:N", sort="-x", title=""),
        )
        st.altair_chart(chart_imp.properties(height=360), use_container_width=True)
        with st.expander("📋 Frequency key"):
            st.markdown(FREQUENCY_KEY)

    col_ports, col_rest = st.columns(2)
    with col_ports:
        if top_ports_loading:
            _dim_header("ports_loading")
            df_pload = pd.DataFrame(top_ports_loading)
            chart_pload = alt.Chart(df_pload).mark_bar(color="#0EA5E9").encode(
                x=alt.X("net_weight:Q", title="Net weight"),
                y=alt.Y("port:N", sort="-x", title=""),
            )
            st.altair_chart(chart_pload.properties(height=280), use_container_width=True)
        if top_ports_discharge:
            _dim_header("ports_discharge")
            df_pdisc = pd.DataFrame(top_ports_discharge)
            chart_pdisc = alt.Chart(df_pdisc).mark_bar(color="#10B981").encode(
                x=alt.X("net_weight:Q", title="Net weight"),
                y=alt.Y("port:N", sort="-x", title=""),
            )
            st.altair_chart(chart_pdisc.properties(height=280), use_container_width=True)
    with col_rest:
        if top_shipping_lines:
            _dim_header("shipping_lines")
            df_ship = pd.DataFrame(top_shipping_lines)
            df_ship["label"] = df_ship["name"].fillna("").apply(lambda s: (s[:35] + "…") if len(s) > 35 else s)
            chart_ship = alt.Chart(df_ship).mark_bar(color="#F59E0B").encode(
                x=alt.X("net_weight:Q", title="Net weight"),
                y=alt.Y("label:N", sort="-x", title=""),
            )
            st.altair_chart(chart_ship.properties(height=280), use_container_width=True)
        if top_hs_codes:
            _dim_header("hs_codes")
            df_hs = pd.DataFrame(top_hs_codes)
            chart_hs = alt.Chart(df_hs).mark_bar(color="#8B5CF6").encode(
                x=alt.X("net_weight:Q", title="Net weight"),
                y=alt.Y("hs_code:N", sort="-x", title=""),
            )
            st.altair_chart(chart_hs.properties(height=280), use_container_width=True)

    st.markdown("### Breakdown by type (by net weight)")
    col_c, col_d = st.columns(2)
    with col_c:
        if cargo_breakdown:
            _dim_header("cargo_type")
            df_cargo = pd.DataFrame(cargo_breakdown)
            chart_cargo = alt.Chart(df_cargo).mark_arc(innerRadius=50).encode(
                theta=alt.Theta("net_weight:Q", title=""),
                color=alt.Color("name:N", scale=alt.Scale(range=COLORS)),
            )
            st.altair_chart(chart_cargo.properties(height=280), use_container_width=True)
    with col_d:
        if package_breakdown:
            _dim_header("package_type")
            df_pkg = pd.DataFrame(package_breakdown)
            chart_pkg = alt.Chart(df_pkg).mark_arc(innerRadius=50).encode(
                theta=alt.Theta("net_weight:Q", title=""),
                color=alt.Color("name:N", scale=alt.Scale(range=COLORS)),
            )
            st.altair_chart(chart_pkg.properties(height=280), use_container_width=True)

    if st.session_state.get("boe_dim_view_more"):
        dimension_view_dialog(st.session_state["boe_dim_view_more"])

    st.markdown("### Records")
    records = data.get("records", [])
    total_records = summary.get("total_items", 0)
    records_page_size = st.session_state.get("boe_records_page_size", DEFAULT_PAGE_SIZE)
    if records_page_size not in PAGE_SIZE_OPTIONS:
        records_page_size = DEFAULT_PAGE_SIZE
        st.session_state["boe_records_page_size"] = records_page_size
    total_pages = max(1, (total_records + records_page_size - 1) // records_page_size)
    current_page = st.session_state.get("boe_table_page", 1)
    current_page = min(max(1, current_page), total_pages)
    st.session_state["boe_table_page"] = current_page

    # If user changed records per page, refetch page 1
    last_limit = st.session_state.get("boe_last_limit_records")
    if last_limit is not None and last_limit != records_page_size:
        st.session_state["boe_table_page"] = 1
        current_page = 1
        params = build_analytics_params(offset=0, page_size=records_page_size)
        with st.spinner("Loading page…"):
            new_data = fetch_analytics(params)
        if new_data:
            st.session_state["boe_analytics_data"] = new_data
            st.session_state["boe_last_limit_records"] = records_page_size
            data = new_data
            records = data.get("records", [])
        st.rerun()

    # Pagination: fetch another page if user clicked Prev/Next
    if "boe_page_next" in st.session_state and st.session_state.pop("boe_page_next", None):
        current_page = min(current_page + 1, total_pages)
        st.session_state["boe_table_page"] = current_page
        params = build_analytics_params(offset=(current_page - 1) * records_page_size, page_size=records_page_size)
        with st.spinner("Loading page…"):
            new_data = fetch_analytics(params)
        if new_data:
            st.session_state["boe_analytics_data"] = new_data
            data = new_data
            records = data.get("records", [])
        st.rerun()
    if "boe_page_prev" in st.session_state and st.session_state.pop("boe_page_prev", None):
        current_page = max(1, current_page - 1)
        st.session_state["boe_table_page"] = current_page
        params = build_analytics_params(offset=(current_page - 1) * records_page_size, page_size=records_page_size)
        with st.spinner("Loading page…"):
            new_data = fetch_analytics(params)
        if new_data:
            st.session_state["boe_analytics_data"] = new_data
            data = new_data
            records = data.get("records", [])
        st.rerun()

    if records:
        # Top of table: Records per page + Download full dataset
        rpp_col, dl_col = st.columns([2, 2])
        with rpp_col:
            st.selectbox(
                "Records per page",
                options=PAGE_SIZE_OPTIONS,
                index=PAGE_SIZE_OPTIONS.index(records_page_size) if records_page_size in PAGE_SIZE_OPTIONS else 1,
                key="boe_records_page_size",
                format_func=lambda x: f"{x} records",
            )
        with dl_col:
            if st.button("Prepare full dataset download", key="boe_prepare_full"):
                export_url = f"{_API_BASE}/reports/boe-header-analytics/export"
                export_params = build_analytics_params(offset=0, page_size=records_page_size)
                export_params.pop("offset", None)
                export_params.pop("limit_records", None)
                flat = []
                for k, v in export_params.items():
                    if isinstance(v, list):
                        for i in v:
                            flat.append((k, i))
                    else:
                        flat.append((k, v))
                with st.spinner("Preparing full dataset…"):
                    try:
                        r = requests.get(export_url, params=flat, timeout=300)
                        r.raise_for_status()
                        st.session_state["boe_export_csv"] = r.content
                        st.rerun()
                    except Exception as e:
                        st.error(f"Export failed: {e}")
            if st.session_state.get("boe_export_csv"):
                st.download_button("Download full dataset (CSV)", data=st.session_state["boe_export_csv"], file_name="boe_analytics_full.csv", mime="text/csv", key="boe_download_full")
        df = pd.DataFrame(records)
        display_cols = [c for c in ["boe_no", "boe_approval_date", "bl_number", "importer_name", "importer_tin", "vessel_carrier", "shipping_line_name", "item_description", "item_hs_code", "port_of_loading", "cargo_type", "gross_weight", "net_weight"] if c in df.columns]
        st.dataframe(df[display_cols] if display_cols else df, use_container_width=True, hide_index=True)

        # Pagination below table
        info_col, prev_col, next_col = st.columns([2, 1, 1])
        with info_col:
            st.caption(f"Page **{current_page}** of **{total_pages}** ({total_records:,} total records)")
        with prev_col:
            if st.button("⬅️ Prev", key="boe_prev_page", disabled=(current_page <= 1), use_container_width=True):
                st.session_state["boe_page_prev"] = True
                st.rerun()
        with next_col:
            if st.button("Next ➡️", key="boe_next_page", disabled=(current_page >= total_pages), use_container_width=True):
                st.session_state["boe_page_next"] = True
                st.rerun()
    else:
        st.caption("No records on this page.")


if __name__ == "__main__":
    main()
