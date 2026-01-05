import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import calendar
from datetime import datetime
import requests
import io

st.set_page_config(layout="centered")
st.title('NOAA Weather Calendar Heatmap')


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

def cleanStationName(rawName):
    if rawName.endswith(' US'):
        rawName = rawName[:-3]
    elif rawName.endswith(', US'):
        rawName = rawName[:-4]
    name = rawName.title()
    if ',' in name:
        parts = name.rsplit(',', 1)
        if len(parts) == 2:
            mainPart = parts[0]
            statePart = parts[1].strip()
            if len(statePart) == 2:
                name = f"{mainPart}, {statePart.upper()}"
    return name
def fetchNoaaData(sid, year, metric, isClimate=False):
    if isClimate:
        dataset = 'normals-daily-1991-2020'
        reqStart = "2010-01-01"
        reqEnd = "2010-12-31"
        dataTypes = 'DLY-TMAX-NORMAL,DLY-TMIN-NORMAL,DLY-TAVG-NORMAL'
    else:
        dataset = 'daily-summaries'
        reqStart = f"{year}-01-01"
        reqEnd = f"{year}-12-31"
        dataTypes = 'TMAX,TMIN,TAVG,PRCP,SNOW,AWND,WSF2,WSF5'
    
    url = (
        f"https://www.ncei.noaa.gov/access/services/data/v1"
        f"?dataset={dataset}"
        f"&stations={sid}"
        f"&startDate={reqStart}"
        f"&endDate={reqEnd}"
        f"&dataTypes={dataTypes}"
        f"&units=standard"
        f"&format=csv"
        f"&includeStationName=true"
    )
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    try:
        r = requests.get(url, headers=headers)
        
        if r.status_code != 200 or "<html" in r.text.lower():
            st.error(f"NOAA API Error: Status {r.status_code}")
            return pd.DataFrame(), sid
            
        df = pd.read_csv(io.StringIO(r.text))
        
        if df.empty or 'DATE' not in df.columns:
            return pd.DataFrame(), sid

        stationName = sid
        if 'NAME' in df.columns and not df['NAME'].dropna().empty:
            raw = df['NAME'].iloc[0]
            stationName = cleanStationName(raw)

        if isClimate:
            df['DATE'] = "2020-" + df['DATE'].astype(str)

        df['DATE'] = pd.to_datetime(df['DATE'])
        
        targetCol = None
        
        if isClimate:
            if 'Maximum' in metric: targetCol = 'DLY-TMAX-NORMAL'
            elif 'Minimum' in metric: targetCol = 'DLY-TMIN-NORMAL'
            else: targetCol = 'DLY-TAVG-NORMAL'
        else:
            if 'Maximum' in metric: targetCol = 'TMAX'
            elif 'Minimum' in metric: targetCol = 'TMIN'
            elif 'Average Temperature' in metric: targetCol = 'TAVG'
            elif 'Precipitation' in metric: targetCol = 'PRCP'
            elif 'Snowfall' in metric: targetCol = 'SNOW'
            elif 'Average wind' in metric: targetCol = 'AWND'
            elif '2-minute' in metric: targetCol = 'WSF2'
            elif '5-second' in metric: targetCol = 'WSF5'
            else: targetCol = 'TMAX'

        # Fallback for TAVG
        if not isClimate and targetCol == 'TAVG' and 'TAVG' not in df.columns:
            if 'TMAX' in df.columns and 'TMIN' in df.columns:
                df['TAVG'] = (df['TMAX'] + df['TMIN']) / 2
            else:
                return pd.DataFrame(), stationName

        if targetCol not in df.columns:
            st.error(f"Metric column {targetCol} not found in data.")
            return pd.DataFrame(), stationName

        df = df[['DATE', targetCol]].rename(columns={targetCol: 'VAL'})
        df['VAL'] = pd.to_numeric(df['VAL'], errors='coerce')
        
        if 'temperature' in metric.lower() or 'wind' in metric.lower() or isClimate:
            df['VAL'] = df['VAL'].round()
        
        df['MD'] = df['DATE'].dt.strftime('%m-%d')
        
        if isClimate:
            targetYear = year if year else 2020
            actualDates = pd.date_range(start=f"{targetYear}-01-01", end=f"{targetYear}-12-31")
            yearDf = pd.DataFrame({'DATE': actualDates})
            yearDf['MD'] = yearDf['DATE'].dt.strftime('%m-%d')
            df = pd.merge(yearDf, df[['MD', 'VAL']], on='MD', how='left')
            
        return df, stationName

    except Exception as e:
        st.error(f"Script Error: {e}")
        return pd.DataFrame(), sid

def renderStationSearch(keySuffix, label="Primary Station"):
    st.subheader(label)
    searchMode = st.radio("Search Method", ["City", "ID"], key=f"sm{keySuffix}", horizontal=True, label_visibility="collapsed")
    
    sid = None
    if searchMode == "City":
        c1, c2 = st.columns([3, 1])
        city = c1.text_input("City Name", key=f"city{keySuffix}")
        if c2.button("Find", key=f"btn{keySuffix}") and city:
            bbox = getBboxFromCity(city)
            st.session_state[f"cand{keySuffix}"] = findStationsAcis(bbox) if bbox else {}
        
        if f"cand{keySuffix}" in st.session_state and st.session_state[f"cand{keySuffix}"]:
            sel = st.selectbox("Select Station", list(st.session_state[f"cand{keySuffix}"].keys()), key=f"sb{keySuffix}")
            sid = st.session_state[f"cand{keySuffix}"][sel]
    else:
        sid = st.text_input("Station ID", value="USW00023169", key=f"txt{keySuffix}").strip().upper()
    return sid

def renderHeatmap(finalDf, titleStr, metricName, isDiffMode, yearForPlot):
    fig, ax = plt.subplots(figsize=(16, 10))
    fig.patch.set_facecolor('black')
    ax.set_facecolor('black')
    
    months = range(1, 13)
    monthLabels = [calendar.month_name[m] for m in months]
    ax.set_xticks(range(1, 32))
    ax.set_xticklabels(range(1, 32), fontsize=10)
    ax.set_yticks(range(12))
    ax.set_yticklabels(monthLabels, fontsize=12)
    ax.set_title(titleStr, color='white', fontsize=18)
    ax.tick_params(colors='white')
    ax.set_xlim(0.5, 32)
    ax.set_ylim(-0.5, 11.5)
    ax.invert_yaxis()
    ax.set_frame_on(False)
    
    # --- COLORS ---
    tempColorScale = [
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

    precipColorScale = [
        (0.00, '#ffffff'), (0.01, '#e0f3db'), (0.10, '#ccebc5'), (0.25, '#a8ddb5'), 
        (0.50, '#7bccc4'), (0.75, '#4eb3d3'), (1.00, '#2b8cbe'), (1.50, '#0868ac'), 
        (2.00, '#084081'), (3.00, '#810f7c'), (4.00, '#4d004b')
    ]

    snowColorScale = [
        (0.0, '#ffffff'), (0.1, '#e0f7fa'), (1.0, '#b2ebf2'), (2.0, '#80deea'), 
        (4.0, '#4dd0e1'), (6.0, '#26c6da'), (8.0, '#00bcd4'), (12.0, '#0097a7'), 
        (18.0, '#006064'), (24.0, '#6a1b9a'), (36.0, '#4a148c')
    ]

    windColorScale = [
        (0, '#ffffff'), (5, '#e5f5e0'), (10, '#a1d99b'), (15, '#41ab5d'), 
        (20, '#fecc5c'), (25, '#fd8d3c'), (30, '#f03b20'), (40, '#bd0026'), 
        (50, '#800026'), (60, '#5a001a'), (70, '#3d0011') 
    ]

    diffColorScale = [
        (-30, '#08306b'), (-20, '#08519c'), (-15, '#2171b5'), (-10, '#4292c6'), 
        (-5, '#6baed6'), (-3, '#9ecae1'), (-1, '#c6dbef'), 
        (0, '#ffffff'),
        (1, '#fee0d2'), (3, '#fcbba1'), (5, '#fc9272'), (10, '#fb6a4a'), 
        (15, '#ef3b2c'), (20, '#cb181d'), (30, '#99000d')
    ]

    activeScale = []
    if isDiffMode:
        activeScale = diffColorScale
    elif 'Precipitation' in metricName:
        activeScale = precipColorScale
    elif 'Snowfall' in metricName:
        activeScale = snowColorScale
    elif 'wind' in metricName.lower(): 
        activeScale = windColorScale
    else:
        activeScale = tempColorScale

    def getColor(val, scale, isDiffMode=False):
        if pd.isna(val): return '#000000'
        if isDiffMode:
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
    
    for i, month in enumerate(months):
        _, numDays = calendar.monthrange(yearForPlot, month)
        for day in range(1, numDays + 1):
            try:
                dateObj = datetime(yearForPlot, month, day)
            except: continue 
            
            row = finalDf.loc[finalDf['DATE'] == dateObj]
            
            if not row.empty:
                val = row['VAL'].values[0]
                if pd.notnull(val):
                    c = getColor(val, activeScale, isDiffMode)
                    rect = plt.Rectangle((day - 0.5, i - 0.5), 1, 1, color=c, ec='black')
                    ax.add_patch(rect)
                    
                    txtCol = 'black'
                    if not isDiffMode:
                        if 'Precipitation' in metricName and val > 1.0: txtCol = 'white'
                        elif 'Snowfall' in metricName and val > 6.0: txtCol = 'white'
                        elif 'wind' in metricName.lower() and val > 30: txtCol = 'white'
                        elif 'temperature' in metricName.lower() and (val < 20 or val > 100):
                            if val < 20: txtCol = 'black' 
                            if val > 100: txtCol = 'white'
                    else:
                        if abs(val) > 20: txtCol = 'white'

                    if ('Precipitation' in metricName or 'Snowfall' in metricName) and not isDiffMode:
                        if val == 0: displayVal = "" 
                        elif val < 1: displayVal = f"{val:.2f}".lstrip('0')
                        else: displayVal = f"{val:.1f}"
                    else:
                        displayVal = int(round(val))
                        
                    ax.text(day, i, displayVal, ha='center', va='center', fontsize=10, color=txtCol)
    
    plt.tight_layout()
    st.pyplot(fig)


years = list(range(1950, 2027))
years.sort(reverse=True)

tab1, tab2 = st.tabs(["Historical Data", "Climate Normals"])

with tab1:
    mode = st.selectbox("Mode", 
        ["Single Station", "Single Station (Two Years)", "Two Stations", "Anomaly"], 
        key="histMode"
    )

    if mode == "Anomaly":
        availMetrics = [
            "Maximum temperature",
            "Minimum temperature",
            "Average Temperature"
        ]
    else:
        availMetrics = [
            "Maximum temperature",
            "Minimum temperature",
            "Average Temperature",
            "Precipitation",
            "Snowfall",
            "Average wind speed",
            "Fastest 2-minute wind speed",
            "Fastest 5-second wind speed"
        ]
        
    metric = st.selectbox("Metric", availMetrics, key="histMetric")
    
    st.markdown("---")
    
    sid1 = renderStationSearch("hist1", "Primary Station")
    
    st.markdown("---")
    
    year1, year2, sid2 = None, None, None
    
    if mode == "Single Station (Two Years)":
        c1, c2 = st.columns(2)
        year1 = c1.selectbox("Primary Year", years, index=1, key="hy1")
        year2 = c2.selectbox("Comparison Year", years, index=10, key="hy2")
        sid2 = sid1
    elif mode == "Anomaly":
        year1 = st.selectbox("Select Year", years, index=1, key="hy1_anom")
        year2 = None 
    else:
        year1 = st.selectbox("Select Year", years, index=1, key="hy1_single")
        year2 = year1
        
    if mode == "Two Stations":
        st.markdown("---")
        sid2 = renderStationSearch("hist2", "Comparison Station")

    st.markdown("---")
    
    if st.button('Generate Calendar', type='primary'):
        if not sid1:
            st.error("Please select a Primary Station.")
        elif mode == "Two Stations" and not sid2:
            st.error("Please select a Comparison Station.")
        else:
            with st.spinner('Fetching Data...'):
                finalDf = pd.DataFrame()
                titleStr = ""
                isDiff = False
                
                if mode == "Anomaly":
                    dfHist, name1 = fetchNoaaData(sid1, year1, metric, isClimate=False)
                    

                    dfNorm, _ = fetchNoaaData(sid1, 2020, metric, isClimate=True)
                    
                    if dfHist.empty:
                        st.error(f"No historical data found for {name1} in {year1}.")
                    elif dfNorm.empty:
                        st.error(f"No Climate Normals found for {name1}. Cannot calculate anomaly.")
                    else:
                        # 3. Merge and Calculate Difference
                        merged = pd.merge(dfHist, dfNorm, on='MD', suffixes=('_hist', '_norm'), how='inner')
                        
                        # Anomaly = Actual - Normal
                        merged['VAL'] = merged['VAL_hist'] - merged['VAL_norm']
                        
                        # Use the Historical Date for the plot
                        merged.rename(columns={'DATE_hist': 'DATE'}, inplace=True)
                        finalDf = merged[['DATE', 'VAL']]
                        
                        titleStr = f"{name1}: {year1} Anomaly\n(vs 1991-2020 Normals)"
                        isDiff = True

                elif mode == "Single Station":
                    df1, name1 = fetchNoaaData(sid1, year1, metric, isClimate=False)
                    if df1.empty: st.error(f"No data for {name1} in {year1}.")
                    else:
                        finalDf = df1
                        titleStr = f"{name1}\n{metric} ({year1})"
                
                elif mode == "Single Station (Two Years)":
                    df1, name1 = fetchNoaaData(sid1, year1, metric, isClimate=False)
                    df2, name2 = fetchNoaaData(sid1, year2, metric, isClimate=False)
                    if df1.empty or df2.empty: st.error("Data missing.")
                    else:
                        merged = pd.merge(df1, df2, on='MD', suffixes=('_1', '_2'), how='left')
                        merged['VAL'] = merged['VAL_1'] - merged['VAL_2']
                        merged.rename(columns={'DATE_1': 'DATE'}, inplace=True)
                        finalDf = merged[['DATE', 'VAL']]
                        titleStr = f"{name1}: {year1} vs {year2}\n{metric}"
                        isDiff = True
                        
                elif mode == "Two Stations":
                    df1, name1 = fetchNoaaData(sid1, year1, metric, isClimate=False)
                    df2, name2 = fetchNoaaData(sid2, year1, metric, isClimate=False)
                    if df1.empty or df2.empty: st.error("Data missing.")
                    else:
                        merged = pd.merge(df1, df2, on='DATE', suffixes=('_1', '_2'), how='outer')
                        merged['VAL'] = merged['VAL_1'] - merged['VAL_2']
                        finalDf = merged[['DATE', 'VAL']]
                        titleStr = f"{name1} vs {name2}\n{metric} ({year1})"
                        isDiff = True
                
                if not finalDf.empty:
                    renderHeatmap(finalDf, titleStr, metric, isDiff, year1)

with tab2:
    modeClim = st.selectbox("Mode", ["Single Station", "Two Stations"], key="climMode")
    metricClim = st.selectbox("Metric", [
        "Maximum temperature",
        "Minimum temperature",
        "Average Temperature"
    ], key="climMetric")
    
    st.markdown("---")
    
    sidClim1 = renderStationSearch("clim1", "Primary Station")
    
    sidClim2 = None
    if modeClim == "Two Stations":
        st.markdown("---")
        sidClim2 = renderStationSearch("clim2", "Comparison Station")
        
    st.markdown("---")
    
    if st.button('Generate Normals Calendar', type='primary'):
        if not sidClim1:
            st.error("Please select a Primary Station.")
        elif modeClim == "Two Stations" and not sidClim2:
            st.error("Please select a Comparison Station.")
        else:
            with st.spinner('Fetching Climate Normals...'):
                displayYear = 2020
                df1, name1 = fetchNoaaData(sidClim1, displayYear, metricClim, isClimate=True)
                
                finalDf = pd.DataFrame()
                titleStr = ""
                isDiff = False
                
                if modeClim == "Single Station":
                    if df1.empty: st.error(f"No normals found for {name1}.")
                    else:
                        finalDf = df1
                        titleStr = f"{name1}\n{metricClim} (1991-2020 Normals)"
                elif modeClim == "Two Stations":
                    df2, name2 = fetchNoaaData(sidClim2, displayYear, metricClim, isClimate=True)
                    if df1.empty or df2.empty: st.error("Normals missing.")
                    else:
                        merged = pd.merge(df1, df2, on='DATE', suffixes=('_1', '_2'), how='outer')
                        merged['VAL'] = merged['VAL_1'] - merged['VAL_2']
                        finalDf = merged[['DATE', 'VAL']]
                        titleStr = f"{name1} vs {name2}\n{metricClim} (Normals)"
                        isDiff = True
                        
                if not finalDf.empty:
                    renderHeatmap(finalDf, titleStr, metricClim, isDiff, displayYear)
