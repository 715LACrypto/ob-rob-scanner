//@version=5
strategy("OB -> ROB Strategy 2 (SHORT, dynamic, LIVE)", overlay=true, max_bars_back=2000, pyramiding=50,
     initial_capital=10000, calc_on_every_tick=true, process_orders_on_close=false,
     max_boxes_count=500, max_lines_count=500, max_labels_count=500)

riskPct   = input.float(0.01, "Risk % per trade (of equity)", step=0.001)

s2MinBars = input.int(10, "Min bars OB->fill (exclusive)")
s2MaxBars = input.int(60, "Max bars OB->fill")
s2MinRisk = input.float(0.02, "Min risk % (entry to SL)", step=0.01)

type GrowingRun
    float obHigh
    float obLow
    float obSize
    int   obIdx
    int   obTime
    int   runLen
    float runExtreme
    int   lastIdx

type PendingSetup
    float obHigh
    float obLow
    float obSize
    float c2High
    int   obIdx
    int   obTime
    int   c2Idx
    bool  distanceFlag
    int   streak

type ActiveROB
    int    obIdx
    float  sl
    float  tp
    float  entryTop
    float  entryMid
    float  entryBottom
    float  pctTop
    float  pctMid
    float  pctBot
    bool   topFilled
    bool   midFilled
    bool   botFilled
    bool   resolved
    int    firstFillIdx
    box    obBox
    line   tpLine
    line   slLine
    line   topLine
    line   midLine
    line   botLine
    label  tpLabel
    label  slLabel
    label  topLabel
    label  midLabel
    label  botLabel

var array<GrowingRun>   growingRuns   = array.new<GrowingRun>()
var array<PendingSetup> pendingSetups = array.new<PendingSetup>()
var array<ActiveROB>    activeROBs    = array.new<ActiveROB>()

deleteRob(ActiveROB rob) =>
    box.delete(rob.obBox)
    line.delete(rob.tpLine)
    line.delete(rob.slLine)
    line.delete(rob.topLine)
    line.delete(rob.midLine)
    line.delete(rob.botLine)
    label.delete(rob.tpLabel)
    label.delete(rob.slLabel)
    label.delete(rob.topLabel)
    label.delete(rob.midLabel)
    label.delete(rob.botLabel)

if barstate.isconfirmed

    if array.size(growingRuns) > 0
        for i = array.size(growingRuns) - 1 to 0
            gr = array.get(growingRuns, i)
            sameDirection = close > open

            if sameDirection
                gr.runLen := gr.runLen + 1
                gr.runExtreme := math.max(gr.runExtreme, high)
                gr.lastIdx := bar_index
                array.set(growingRuns, i, gr)
            else
                if gr.runLen >= 2
                    imbalance = gr.runExtreme - gr.obHigh
                    if imbalance >= gr.obSize
                        ps = PendingSetup.new(gr.obHigh, gr.obLow, gr.obSize, gr.runExtreme,
                             gr.obIdx, gr.obTime, gr.lastIdx, false, 0)
                        array.push(pendingSetups, ps)
                array.remove(growingRuns, i)

    if bar_index >= 1
        obOpen  = open[1]
        obClose = close[1]
        obHigh  = high[1]
        obLow   = low[1]
        obSize  = obHigh - obLow

        if obClose < obOpen and close > open and obSize > 0
            gr = GrowingRun.new(obHigh, obLow, obSize, bar_index - 1, time[1], 1, high, bar_index)
            array.push(growingRuns, gr)

    if array.size(pendingSetups) > 0
        for i = array.size(pendingSetups) - 1 to 0
            ps = array.get(pendingSetups, i)

            if bar_index > ps.c2Idx
                if not ps.distanceFlag and (ps.obLow - low) >= ps.obSize
                    ps.distanceFlag := true
                if close < ps.obLow
                    ps.streak := ps.streak + 1
                else
                    ps.streak := 0

                if ps.distanceFlag and ps.streak >= 2
                    sl = ps.c2High
                    tp = ps.obLow - (ps.c2High - ps.obLow)
                    entryTop = ps.obHigh
                    entryBot = ps.obLow
                    entryMid = (ps.obHigh + ps.obLow) / 2.0
                    pctTop = math.abs(entryTop - sl) / entryTop
                    pctMid = math.abs(entryMid - sl) / entryMid
                    pctBot = math.abs(entryBot - sl) / entryBot

                    dirColor = color.red
                    obBx = box.new(ps.obTime, entryTop, time_close, entryBot, xloc=xloc.bar_time,
                         border_color=color.new(dirColor, 0), bgcolor=color.new(dirColor, 88), extend=extend.right)

                    rrTop = math.abs(tp - entryTop) / math.abs(entryTop - sl)
                    rrMid = math.abs(tp - entryMid) / math.abs(entryMid - sl)
                    rrBot = math.abs(tp - entryBot) / math.abs(entryBot - sl)

                    tpL  = line.new(time, tp, time_close, tp, xloc=xloc.bar_time, color=color.new(color.purple, 0), style=line.style_dashed, width=1, extend=extend.right)
                    slL  = line.new(time, sl, time_close, sl, xloc=xloc.bar_time, color=color.new(color.red, 0), style=line.style_dashed, width=1, extend=extend.right)
                    topL = line.new(ps.obTime, entryTop, time_close, entryTop, xloc=xloc.bar_time, color=color.new(dirColor, 0), style=line.style_solid, extend=extend.right)
                    midL = line.new(ps.obTime, entryMid, time_close, entryMid, xloc=xloc.bar_time, color=color.new(dirColor, 30), style=line.style_dashed, extend=extend.right)
                    botL = line.new(ps.obTime, entryBot, time_close, entryBot, xloc=xloc.bar_time, color=color.new(dirColor, 0), style=line.style_solid, extend=extend.right)

                    tpLbl  = label.new(time_close, tp, "TP " + str.tostring(tp, format.mintick), xloc=xloc.bar_time, style=label.style_label_left, color=color.new(color.purple, 70), textcolor=color.white, size=size.small)
                    slLbl  = label.new(time_close, sl, "SL " + str.tostring(sl, format.mintick), xloc=xloc.bar_time, style=label.style_label_left, color=color.new(color.red, 70), textcolor=color.white, size=size.small)
                    topLbl = label.new(time_close, entryTop, str.tostring(entryTop, format.mintick) + "  " + str.tostring(rrTop, "#.##") + "R", xloc=xloc.bar_time, style=label.style_label_left, color=color.new(dirColor, 70), textcolor=color.white, size=size.small)
                    midLbl = label.new(time_close, entryMid, str.tostring(entryMid, format.mintick) + "  " + str.tostring(rrMid, "#.##") + "R", xloc=xloc.bar_time, style=label.style_label_left, color=color.new(dirColor, 70), textcolor=color.white, size=size.small)
                    botLbl = label.new(time_close, entryBot, str.tostring(entryBot, format.mintick) + "  " + str.tostring(rrBot, "#.##") + "R", xloc=xloc.bar_time, style=label.style_label_left, color=color.new(dirColor, 70), textcolor=color.white, size=size.small)

                    rob = ActiveROB.new(ps.obIdx, sl, tp, entryTop, entryMid, entryBot, pctTop, pctMid, pctBot,
                         false, false, false, false, na, obBx, tpL, slL, topL, midL, botL, tpLbl, slLbl, topLbl, midLbl, botLbl)
                    array.push(activeROBs, rob)

                    array.remove(pendingSetups, i)

if array.size(activeROBs) > 0
    for j = array.size(activeROBs) - 1 to 0
        rob = array.get(activeROBs, j)
        if not rob.resolved
            barsFromOB = bar_index - rob.obIdx

            // ---- entry fills (checked first, same as before) ----
            if not rob.topFilled and low <= rob.entryTop and high >= rob.entryTop and bar_index > rob.obIdx
                rob.topFilled := true
                array.set(activeROBs, j, rob)
                if barsFromOB > s2MinBars and barsFromOB <= s2MaxBars and rob.pctTop > s2MinRisk
                    if na(rob.firstFillIdx)
                        rob.firstFillIdx := bar_index
                        array.set(activeROBs, j, rob)
                    riskAmountT = strategy.equity * riskPct
                    perUnitRiskT = math.abs(rob.entryTop - rob.sl)
                    qtyT = perUnitRiskT > 0 ? riskAmountT / perUnitRiskT : 0
                    strategy.entry("T_" + str.tostring(rob.obIdx), strategy.short, qty=qtyT, limit=rob.entryTop)
                    strategy.exit("TX_" + str.tostring(rob.obIdx), from_entry="T_" + str.tostring(rob.obIdx), stop=rob.sl, limit=rob.tp)
                    if barstate.isrealtime
                        alert('{"secret":"rob2026secret","symbol":"' + syminfo.basecurrency + '-' + syminfo.currency + '","sl":' + str.tostring(rob.sl) + ',"tp":' + str.tostring(rob.tp) + '}', alert.freq_once_per_bar)

            if not rob.midFilled and low <= rob.entryMid and high >= rob.entryMid and bar_index > rob.obIdx
                rob.midFilled := true
                array.set(activeROBs, j, rob)
                if barsFromOB > s2MinBars and barsFromOB <= s2MaxBars and rob.pctMid > s2MinRisk
                    if na(rob.firstFillIdx)
                        rob.firstFillIdx := bar_index
                        array.set(activeROBs, j, rob)
                    riskAmountM = strategy.equity * riskPct
                    perUnitRiskM = math.abs(rob.entryMid - rob.sl)
                    qtyM = perUnitRiskM > 0 ? riskAmountM / perUnitRiskM : 0
                    strategy.entry("M_" + str.tostring(rob.obIdx), strategy.short, qty=qtyM, limit=rob.entryMid)
                    strategy.exit("MX_" + str.tostring(rob.obIdx), from_entry="M_" + str.tostring(rob.obIdx), stop=rob.sl, limit=rob.tp)
                    if barstate.isrealtime
                        alert('{"secret":"rob2026secret","symbol":"' + syminfo.basecurrency + '-' + syminfo.currency + '","sl":' + str.tostring(rob.sl) + ',"tp":' + str.tostring(rob.tp) + '}', alert.freq_once_per_bar)

            if not rob.botFilled and low <= rob.entryBottom and high >= rob.entryBottom and bar_index > rob.obIdx
                rob.botFilled := true
                array.set(activeROBs, j, rob)
                if barsFromOB > s2MinBars and barsFromOB <= s2MaxBars and rob.pctBot > s2MinRisk
                    if na(rob.firstFillIdx)
                        rob.firstFillIdx := bar_index
                        array.set(activeROBs, j, rob)
                    riskAmountB = strategy.equity * riskPct
                    perUnitRiskB = math.abs(rob.entryBottom - rob.sl)
                    qtyB = perUnitRiskB > 0 ? riskAmountB / perUnitRiskB : 0
                    strategy.entry("B_" + str.tostring(rob.obIdx), strategy.short, qty=qtyB, limit=rob.entryBottom)
                    strategy.exit("BX_" + str.tostring(rob.obIdx), from_entry="B_" + str.tostring(rob.obIdx), stop=rob.sl, limit=rob.tp)
                    if barstate.isrealtime
                        alert('{"secret":"rob2026secret","symbol":"' + syminfo.basecurrency + '-' + syminfo.currency + '","sl":' + str.tostring(rob.sl) + ',"tp":' + str.tostring(rob.tp) + '}', alert.freq_once_per_bar)

            // ---- NEW: kill switch. Once ANY filled entry's price hits TP or SL, ----
            // ---- the whole ROB is done - cancel anything unfilled, delete the box. ----
            anyFilled = rob.topFilled or rob.midFilled or rob.botFilled
            hitTP = low <= rob.tp and high >= rob.tp
            hitSL = low <= rob.sl and high >= rob.sl

            if anyFilled and (hitTP or hitSL)
                // cancel any entries that never got filled, so they can't fire later
                if not rob.topFilled
                    strategy.cancel("T_" + str.tostring(rob.obIdx))
                if not rob.midFilled
                    strategy.cancel("M_" + str.tostring(rob.obIdx))
                if not rob.botFilled
                    strategy.cancel("B_" + str.tostring(rob.obIdx))
                deleteRob(rob)
                rob.resolved := true
                array.set(activeROBs, j, rob)

            // ---- timeout ----
            // If nothing has fired yet, give up based on bars since the OB candle.
            // If something HAS fired, give that real trade its own full 65 bars
            // from when IT fired, not from the OB - so a late entry (near bar 60)
            // still gets a fair shot instead of almost no time left on the clock.
            else if na(rob.firstFillIdx) and barsFromOB > s2MaxBars + 5
                strategy.cancel("T_" + str.tostring(rob.obIdx))
                strategy.cancel("M_" + str.tostring(rob.obIdx))
                strategy.cancel("B_" + str.tostring(rob.obIdx))
                deleteRob(rob)
                rob.resolved := true
                array.set(activeROBs, j, rob)

            else if not na(rob.firstFillIdx) and (bar_index - rob.firstFillIdx) > s2MaxBars + 5
                strategy.cancel("T_" + str.tostring(rob.obIdx))
                strategy.cancel("M_" + str.tostring(rob.obIdx))
                strategy.cancel("B_" + str.tostring(rob.obIdx))
                deleteRob(rob)
                rob.resolved := true
                array.set(activeROBs, j, rob)

        if rob.resolved
            array.remove(activeROBs, j)
