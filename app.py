import streamlit as st
import pandas as pd
from dataclasses import asdict
from main import scrape_places
import time
import asyncio
import sys

# Fix for Windows asyncio loop policy
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

st.set_page_config(page_title="Beyond Ads Scraper", page_icon="🚀")

st.title("🚀 Beyond Ads Scraper")
st.markdown("Customize your search and extract business data easily.")

# Lists for Dropdowns
AREAS = [
    "Beirut", "Tripoli", "Sidon (Saida)", "Tyre (Sour)", "Jounieh", "Zahle", 
    "Nabatieh", "Baalbek", "Byblos (Jbeil)", "Batroun", "Aley", "Bhamdoun", "Broummana"
]

INDUSTRIES = [
    "Real Estate Companies", "Roofing Contractors", "Dentists", "Restaurants", 
    "Law Firms", "Hotels", "Hospitals", "Supermarkets", "Pharmacies", 
    "Schools", "Universities", "Gyms", "Car Rental", "Travel Agencies", "Banks"
]

# Input Form
with st.form("scrape_form"):
    col1, col2 = st.columns(2)
    
    with col1:
        # Industry Selection
        industry_input = st.selectbox("Select Industry", INDUSTRIES)
        # Option to add custom industry
        custom_industry = st.checkbox("Type custom industry?")
        if custom_industry:
            industry_input = st.text_input("Custom Industry", value="")

    with col2:
        # Area Selection
        area_input = st.selectbox("Select Area", AREAS)
        # Option to add custom area
        custom_area = st.checkbox("Type custom area?")
        if custom_area:
            area_input = st.text_input("Custom Area", value="")
            
    total_results = st.number_input("Max Results", min_value=1, max_value=500, value=5, step=1)
    
    submitted = st.form_submit_button("🚀 Start Scraping")

if submitted:
    # Construct Search Query
    if industry_input and area_input:
        search_query = f"{industry_input} in {area_input}, Lebanon"
    else:
        st.error("Please provide both Industry and Area.")
        st.stop()
        
    status_placeholder = st.empty()
    progress_bar = st.progress(0)
    
    status_placeholder.info(f"Starting scraper for: **{search_query}**... Please wait.")
    
    def progress_callback(current, total, message=None):
        if total > 0:
            percent = int((current / total) * 100)
            progress_bar.progress(min(percent, 100))
        
        if message:
            status_placeholder.info(f"{message} ({current}/{total})")
        else:
            status_placeholder.info(f"Collected {current} of {total} required...")

    try:
        # Extract strict area name (e.g. "Sidon (Saida)" -> "Sidon")
        # If user typed custom area, use it as is.
        strict_area_filter = None
        excluded_areas_list = []
        
        if area_input:
            # If it comes from the dropdown list, it might have parens
            if "(" in area_input:
                strict_area_filter = area_input.split("(")[0].strip()
            else:
                strict_area_filter = area_input
                
            # Build exclusion list (all other areas from the main list)
            # This prevents "Jounieh" results from appearing in "Beirut" searches
            # (e.g. "Beirut Highway, Jounieh")
            for area in AREAS:
                clean_area = area.split("(")[0].strip()
                if clean_area.lower() != strict_area_filter.lower():
                    excluded_areas_list.append(clean_area)

        # Run the scraper
        result = scrape_places(
            search_query, 
            total_results, 
            callback=progress_callback, 
            required_area=strict_area_filter,
            excluded_areas=excluded_areas_list
        )
        places = result["places"]
        
        # Finish progress bar
        progress_bar.progress(100)
        status_placeholder.empty()
        
        if places:
            # Convert to DataFrame
            df = pd.DataFrame([asdict(place) for place in places])
            
            # Show success message
            status_placeholder.success(f"✅ Found {len(df)} businesses for '{search_query}'!")
            
            if result["filtered_count"] > 0:
                st.warning(f"⚠️ Note: {result['filtered_count']} results were hidden because their address did not contain '{strict_area_filter}'.")
            
            # Display Data
            st.dataframe(df)
            
            # Dynamic Filename: Scrape_Industry_Count.xlsx
            # Clean industry name for filename (remove spaces/special chars if needed, but simple replace is usually enough)
            safe_industry = industry_input.replace(" ", "_").replace("/", "-")
            safe_area = area_input.replace(" ", "_").replace("/", "-")
            filename = f"Scrape_{safe_industry}_{len(df)}.xlsx"

            # Download Button (Excel format)
            import io
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='Sheet1')
            
            st.download_button(
                label="📥 Download Excel",
                data=buffer.getvalue(),
                file_name=filename,
                mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            )

        else:
            if result["total_found"] > 0 and result["filtered_count"] > 0:
                 status_placeholder.error(f"⚠️ Found {result['total_found']} results, but ALL were filtered out because they didn't match '{strict_area_filter}'.")
            else:
                 status_placeholder.warning("⚠️ No results found. Try a different query.")
            
    except Exception as e:
        status_placeholder.error(f"❌ An error occurred: {str(e)}")
