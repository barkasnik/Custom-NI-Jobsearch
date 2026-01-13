import streamlit as st

st.title("Job Sources")

st.write("This app uses RSS feeds so it can run on Streamlit Cloud with no keys.")

st.subheader("UK Civil Service (via Indeed RSS)")
st.write(
    "We pull Indeed RSS results filtered to links that come from the official Civil Service Jobs domain "
    "and NI locations."
)
st.code("https://rss.indeed.com/rss?q=site:civilservicejobs.service.gov.uk+Belfast&l=Northern+Ireland")

st.subheader("Careerjet RSS")
st.write("We pull Careerjet RSS for Northern Ireland and filter out NICS listings.")
st.code("https://rss.careerjet.co.uk/rss?s=HMRC&l=Northern+Ireland&sort=date")

st.caption("Note: We do NOT scrape Civil Service Jobs directly because it requires JavaScript and a 'Quick check' step.")
