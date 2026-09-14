# Trip Analysis — Questions to Answer

**Scope:** Driver 4362 Trip Settlement Log (3 trips / TS Nos) cross-referenced with the 9118 leg-level detail report (12 legs), covering trips completed in August 2026.

**Data sources:**
- `TSL` = Trip Settlement Log (trip-level: freight, expenses, contribution, days, driver account)
- `LEG` = 9118 leg-level report (loading/unloading/transit timestamps, distance, freight, client, material — join key: `TS No`)

---

## 1. Trip Time Breakdown

**Q1.** What is the loading time, unloading time, and transit time for each trip (TS No) in the Trip Settlement Log, and what share of total trip duration does each phase represent?
*(LEG — timestamps: S For Loading, Loading Complete, Reach Destination, Unloading Complete)*

---

## 2. Contribution/KM Diagnostics

**Q2.** Is a low Contribution/KM explained by low freight, high distance, high direct expense, idle time, or a combination of these? Which factor(s) correlate most strongly with low Contribution/KM across trips?
*(TSL — Freight, KMs, Direct Exp, Idle Days; LEG — idle/gap hours from Q1)*

---

## 3. Efficiency & Utilization

**Q3.** What is the loaded-vs-empty ratio (by distance and by time) for each trip and each vehicle?
*(TSL — Ld/Empty KMs & Days; LEG — leg-level distance & time by loaded/empty status)*

**Q4.** How does turnaround time (total trip duration) trend across the month of August?
*(TSL — From Dt/To Dt; LEG — trip duration from Q1)*

**Q5.** Does idle/waiting time cluster around specific routes, offices, or drivers? What's the primary driver of idle time?
*(LEG — gap-between-legs from Q1; TSL — Idle Days, Driver, TS Office)*

---

## 4. Profitability & Cost

**Q6.** What is the contribution margin per trip, per KM, and per day, and how does it rank across trips?
*(TSL — Contribution Per Day, Per KM)*

**Q7.** What is the direct-expense-to-freight ratio (%) per trip, and which trips have unusually high cost ratios?
*(TSL — Direct Exp Amt, %, Freight Bkg/Mkt)*

**Q8.** What is the freight rate per KM by client, material, and route? Which lanes/clients pay best?
*(LEG — Mkt Freight, Distance, Client, Material, Route)*

---

## 5. Driver & Vehicle Performance

**Q9.** How do drivers (SHAMSHAD vs SAHAJAD) compare on transit speed, idle time, and on-time loading performance?
*(LEG — Driver Name, timestamps; TSL — Driver)*

**Q10.** What is each driver's settlement position — advance given vs closing balance — and are any drivers running a persistent deficit?
*(TSL — Driver Account: Advance, +/-, Closing Balance)*

**Q11.** How do vehicles compare on KM driven, loaded %, and revenue efficiency (freight per KM)?
*(TSL — Vehicle No, KMs, Freight; LEG — Vehicle)*

---

## 6. Schedule Adherence

**Q12.** What is the delay between scheduled loading (S For Loading) and actual loading completion, per leg? Which legs/routes show the largest dispatch delays?
*(LEG — S For Loading, Loading Complete, Route)*

---

## 7. Route / Leg-Level Analysis

**Q13.** Which legs are distance/transit-time outliers — i.e., took unusually long relative to distance covered?
*(LEG — Distance, Transit Time from Q1)*

**Q14.** What is the impact of empty/repositioning legs on trip-level contribution — how much distance and time is run with zero freight, and what does it cost in lost productive time?
*(LEG — legs with zero freight; TSL — Contribution)*

---

*Note: Sample size is small (3 trips, 12 legs), so results should be read as directional rather than statistically robust. Q1 and Q2 are the priority items for this pass.*
