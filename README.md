# Beyond Ads Scraper 🚀

A customizable tool to scrape business data (Phone numbers, Instagram links, Addresses) from Google Maps, tailored for Lebanese industries and areas.

## Features
- **Targeted Search**: Select specific industries (e.g., Real Estate, Pharmacies) and areas (e.g., Beirut, Tripoli).
- **Smart Filtering**: 
  - Validates and formats Lebanese phone numbers (Mobile vs Landline).
  - Filters out social media links (Instagram/Facebook) from the "Website" field.
  - Strict address filtering to ensure results match the requested area.
- **Deduplication**: Automatically removes duplicate entries.
- **Export**: Download results as a CSV file compatible with Excel.

## Deployment
This app is ready for deployment on **Streamlit Community Cloud**.
1. Push this code to GitHub.
2. Connect your repository on [share.streamlit.io](https://share.streamlit.io).
3. The app will automatically install Chrome and dependencies using `packages.txt`.

## Local Usage
1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   playwright install
   ```
2. Run the app:
   ```bash
   streamlit run app.py
   ```
