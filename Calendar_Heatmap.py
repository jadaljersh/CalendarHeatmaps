import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import calendar
from datetime import datetime
import requests

st.set_page_config(layout="centered")
st.title('Historical Weather Dataset Calendar Heatmap')

@st.cache_data
def getBboxFromCity(cityName):
    url = "https://nominatim.openstreetmap.org/search"
    headers = {'User-Agent': 'StreamlitWeatherApp/1.0'}
    params = {'q': cityName, 'format': 'json', 'limit': 1}
    try:
        r = requests.get(url, headers=headers, params=params)
        data = r.json()
        if data:
            b = [float(x) for x in data[0]['boundingbox']]
            minLat, maxLat, minLon, maxLon = b[0], b[1], b[2], b[3]
            pad = 0.3 
            return [minLon - pad, minLat - pad, maxLon + pad, maxLat + pad]
    except:
        return None
    return None

@st.cache_data
def findStationsAcis(bbox):
    url = "http://data.rcc-acis.org/StnMeta"
    params = {"bbox": bbox, "meta": "name,sids", "elems": "maxt"}
    try:
        r = requests.post(url, json=params)
        data = r.json()
        stations = {}
        if 'meta' in data:
            for item in data['meta']:
                name = item['name'].title()
                sids = item['sids']
                noaaId = None
                for sidStr in sids:
                    sid = sidStr.split()[0]
                    if sid.startswith('USW') or sid.startswith('USC'):
                        noaaId = sid
                        break
                if not noaaId:
                     for sidStr in sids:
                        sid = sidStr.split()[0]
                        if len(sid) == 11:
                            noaaId = sid
                            break     
                if noaaId:
                    stations[f"{name} ({noaaId})"] = noaaId
        return dict(sorted(stations.items()))
    except:
        return {}

def fetchNoaaData(sid, year, metric):
    startDate = f"{year}-01-01"
    endDate = f"{year}-12-31"
    dataTypes = 'TMAX,TMIN,TAVG'
    
    url = (
        f"https://www.ncei.noaa.gov/access/services/data/v1"
        f"?dataset=daily-summaries"
        f"&stations={sid}"
        f"&startDate={startDate}"
        f"&endDate={endDate}"
        f"&dataTypes={dataTypes}"
        f"&units=standard"
        f"&format=csv"
        f"&includeStationName=true"
    )
    
    try:
        df = pd.read_csv(url)
        if df.empty or 'DATE' not in df.columns:
            return pd.DataFrame(), sid

        stationName = sid
        if 'NAME' in df.columns and not df['NAME'].dropna().empty:
            stationName = df['NAME'].iloc[0].title()

        df['DATE'] = pd.to_datetime(df['DATE'])
        
        targetCol = 'TMAX' if 'High' in metric else 'TMIN' if 'Low' in metric else 'TAVG'

        if targetCol == 'TAVG' and 'TAVG' not in df.columns:
            if 'TMAX' in df.columns and 'TMIN' in df.columns:
                df['TAVG'] = (df['TMAX'] + df['TMIN']) / 2
            else:
                return pd.DataFrame(), stationName

        if targetCol not in df.columns:
            return pd.DataFrame(), stationName

        df = df[['DATE', targetCol]].rename(columns={targetCol: 'VAL'})
        df['VAL'] = pd.to_numeric(df['VAL'], errors='coerce')
        if 'Average' in metric: df['VAL'] = df['VAL'].round()
        
        df['MD'] = df['DATE'].dt.strftime('%m-%d')
            
        return df, stationName
    except Exception:
        return pd.DataFrame(), sid

mode = st.selectbox("Mode", ["Single Station", "Two Years, Single Station", "Two Stations"])
tempChoice = st.selectbox("Metric", ['High Temperature', 'Low Temperature', 'Average Temperature'])

st.markdown("---")

years = list(range(1950, 2027))
years.sort(reverse=True)
stationId1, stationId2 = None, None
year1, year2 = None, None

st.subheader("Primary Station")

searchMode1 = st.radio("Search Method", ["City", "ID"], key="sm1", horizontal=True, label_visibility="collapsed")

if searchMode1 == "City":
    city1 = st.text_input("City Name", key="city1")
    if st.button("Find", key="btn1") and city1:
        bbox = getBboxFromCity(city1)
        st.session_state.cand1 = findStationsAcis(bbox) if bbox else {}
    
    if 'cand1' in st.session_state and st.session_state.cand1:
        sel1 = st.selectbox("Select Station", list(st.session_state.cand1.keys()), key="sb1")
        stationId1 = st.session_state.cand1[sel1]
else:
    stationId1 = st.text_input("Station ID", value="USW00023169", key="txt1").strip().upper()

st.markdown("---")

if mode == "Two Years, Single Station":
    colY1, colY2 = st.columns(2)
    year1 = colY1.selectbox("Primary Year", years, index=1)
    year2 = colY2.selectbox("Comparison Year", years, index=10)
    stationId2 = stationId1
else:
    year1 = st.selectbox("Select Year", years, index=1)
    year2 = year1

if mode == "Two Stations":
    st.markdown("---")
    st.subheader("Comparison Station")
    
    searchMode2 = st.radio("Search Method", ["City", "ID"], key="sm2", horizontal=True, label_visibility="collapsed")
    
    if searchMode2 == "City":
        city2 = st.text_input("City Name", key="city2")
        if st.button("Find", key="btn2") and city2:
            bbox = getBboxFromCity(city2)
            st.session_state.cand2 = findStationsAcis(bbox) if bbox else {}
        
        if 'cand2' in st.session_state and st.session_state.cand2:
            sel2 = st.selectbox("Select Station", list(st.session_state.cand2.keys()), key="sb2")
            stationId2 = st.session_state.cand2[sel2]
    else:
        stationId2 = st.text_input("Station ID", value="USW00023112", key="txt2").strip().upper()

st.markdown("---")

if st.button('Generate Calendar', type='primary'):
    if not stationId1:
        st.error("Please select a Primary Station.")
    elif mode == "Two Stations" and not stationId2:
        st.error("Please select a Comparison Station.")
    else:
        with st.spinner('Fetching Data...'):
            df1, name1 = fetchNoaaData(stationId1, year1, tempChoice)
            
            finalDf = pd.DataFrame()
            titleStr = ""
            isDiffMode = False
            
            if mode == "Single Station":
                if df1.empty:
                    st.error(f"No data found for {name1} in {year1}.")
                else:
                    finalDf = df1
                    titleStr = f"{name1}\n{tempChoice} ({year1})"
                    isDiffMode = False

            elif mode == "Two Years, Single Station":
                df2, name2 = fetchNoaaData(stationId1, year2, tempChoice)
                
                if df1.empty or df2.empty:
                    st.error("Data missing for one or both years.")
                else:
                    merged = pd.merge(df1, df2, on='MD', suffixes=('_1', '_2'), how='left')
                    merged['VAL'] = merged['VAL_1'] - merged['VAL_2']
                    merged.rename(columns={'DATE_1': 'DATE'}, inplace=True)
                    finalDf = merged[['DATE', 'VAL']]
                    titleStr = f"{name1}: {year1} vs {year2}\n{tempChoice}"
                    isDiffMode = True

            elif mode == "Two Stations":
                df2, name2 = fetchNoaaData(stationId2, year1, tempChoice)
                
                if df1.empty or df2.empty:
                    st.error("Data missing for one or both stations.")
                else:
                    merged = pd.merge(df1, df2, on='DATE', suffixes=('_1', '_2'), how='outer')
                    merged['VAL'] = merged['VAL_1'] - merged['VAL_2']
                    finalDf = merged[['DATE', 'VAL']]
                    titleStr = f"{name1} vs {name2}\n{tempChoice} ({year1})"
                    isDiffMode = True

            if not finalDf.empty:
                fig, ax = plt.subplots(figsize=(16, 10))
                fig.patch.set_facecolor('black')
                ax.set_facecolor('black')
                
                months = range(1, 13)
                monthLabels = [calendar.month_name[m] for m in months]
                ax.set_xticks(range(1, 32))
                ax.set_xticklabels(range(1, 32), fontsize=8)
                ax.set_yticks(range(12))
                ax.set_yticklabels(monthLabels, fontsize=10)
                ax.set_title(titleStr, color='white', fontsize=16)
                ax.tick_params(colors='white')
                ax.set_xlim(0.5, 32)
                ax.set_ylim(-0.5, 11.5)
                ax.invert_yaxis()
                ax.set_frame_on(False)
                
                absColorScale = [
                    (0, '#E4E4F7'), (2, '#E4E1FD'), (4, '#DBCBFF'), (6, '#D1A9FF'), (8, '#BF88FF'), 
                    (10, '#A373E5'), (12, '#8F5BBF'), (14, '#733DA3'), (16, '#5D2F8F'), (18, '#420078'), 
                    (20, '#32007E'), (22, '#2A0099'), (24, '#1400A0'), (32, '#0f51d4'), (34, '#0f75d4'), 
                    (36, '#0f8cd4'), (38, '#0fa6d4'), (40, '#0fbdd4'), (45, '#00e8e8'), (47, '#00e8d0'), 
                    (48, '#00e8d0'), (49, '#00e8d0'), (50, '#00e8d0'), (51, '#4edec9'), (52, '#4edec9'), 
                    (53, '#4ddfb4'), (54, '#4ddfb4'), (55, '#1cb769'), (56, '#1cb769'), (57, '#1cb769'), 
                    (58, '#1cb769'), (59, '#1cb769'), (60, '#42b51b'), (61, '#42b51b'), (62, '#42b51b'), 
                    (63, '#42b51b'), (64, '#42b51b'), (65, '#42b51b'), (66, '#aae71d'), (67, '#aae71d'), 
                    (68, '#aae71d'), (69, '#aae71d'), (70, '#aae71d'), (71, '#defe01'), (72, '#defe01'), 
                    (73, '#fff200'), (74, '#fff200'), (75, '#ffdb0f'), (76, '#ffdb0f'), (77, '#ffdb0f'), 
                    (78, '#ffb10f'), (79, '#ffb10f'), (80, '#ff990f'), (81, '#ff990f'), (82, '#ff810f'), 
                    (83, '#ff810f'), (84, '#ff450f'), (85, '#ff450f'), (86, '#ed1c24'), (87, '#ed1c24'), 
                    (88, '#ed1c24'), (89, '#ed1c24'), (90, '#ed1c24'), (91, '#ed1c24'), (92, '#ed1c24'), 
                    (93, '#ed1c24'), (94, '#ed1c24'), (95, '#ed1c24'), (96, '#db111c'), (97, '#db111c'), 
                    (98, '#db111c'), (99, '#db111c'), (100, '#cf0e3f'), (101, '#cf0e3f'), (102, '#c10d63'), 
                    (103, '#c10d63'), (104, '#f578b4'), (105, '#f02686'), (106, '#f02686'), (107, '#f34e9c'), 
                    (108, '#f34e9c'), (109, '#f578b4'), (110, '#f578b4'), (111, '#f578b4'), (112, '#f578b4'), 
                    (113, '#fcabfa'), (114, '#fcabfa'), (115, '#fcabfa'), (116, '#fcabfa'), (117, '#cd00f9'), 
                    (118, '#cd00f9'), (119, '#cd00f9'), (120, '#cd00f9'), (121, '#cd00f9')
                ]
                diffColorScale = [
                    (-30, '#08306b'), (-20, '#08519c'), (-15, '#2171b5'), (-10, '#4292c6'), 
                    (-5, '#6baed6'), (-3, '#9ecae1'), (-1, '#c6dbef'), 
                    (0, '#ffffff'),
                    (1, '#fee0d2'), (3, '#fcbba1'), (5, '#fc9272'), (10, '#fb6a4a'), 
                    (15, '#ef3b2c'), (20, '#cb181d'), (30, '#99000d')
                ]
                def getColor(val, scale, isDiff=False):
                    if pd.isna(val): return '#000000'
                    if isDiff:
                        sortedScale = sorted(scale, key=lambda x: x[0])
                        if val <= sortedScale[0][0]: return sortedScale[0][1]
                        if val >= sortedScale[-1][0]: return sortedScale[-1][1]
                        for i in range(len(sortedScale)-1):
                            low, colLow = sortedScale[i]
                            high, colHigh = sortedScale[i+1]
                            if low <= val < high:
                                if val == 0: return '#ffffff'
                                return colLow if val < 0 else colHigh
                        return sortedScale[-1][1]
                    else:
                        for threshold, color in reversed(scale):
                            if val >= threshold: return color
                        return '#ffffff'

                activeScale = diffColorScale if isDiffMode else absColorScale
                
                for i, month in enumerate(months):
                    _, numDays = calendar.monthrange(year1, month)
                    for day in range(1, numDays + 1):
                        try:
                            dateObj = datetime(year1, month, day)
                        except: continue 
                        
                        row = finalDf.loc[finalDf['DATE'] == dateObj]
                        
                        if not row.empty:
                            val = row['VAL'].values[0]
                            if pd.notnull(val):
                                c = getColor(val, activeScale, isDiffMode)
                                rect = plt.Rectangle((day - 0.5, i - 0.5), 1, 1, color=c, ec='black')
                                ax.add_patch(rect)
                                txtCol = 'black'
                                if isDiffMode and (val <= -20 or val >= 20): txtCol = 'white'
                                elif not isDiffMode and (val < 20 or val > 100):
                                    if val < 20: txtCol = 'black' 
                                    if val > 100: txtCol = 'white'
                                displayVal = int(round(val))
                                ax.text(day, i, displayVal, ha='center', va='center', fontsize=10, color=txtCol)
                
                plt.tight_layout()
                st.pyplot(fig)