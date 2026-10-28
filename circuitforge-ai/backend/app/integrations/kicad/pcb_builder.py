"""Runs in a SUBPROCESS (needs KiCad's `pcbnew` Python module). stdin: JSON {components, outdir}. stdout: JSON result.
Layout: one row of through-hole parts; each net gets a B.Cu channel; each pad drops an F.Cu stub to a via on its channel.
This simple scheme is correct for small single-row boards and is verified with KiCad's own DRC, not assumed."""
import json, math, sys
import pcbnew
from pcbnew import FromMM, ToMM, VECTOR2I

LIB = "/usr/share/kicad/footprints"
FP = {"R": ("Resistor_THT", "R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal", 0),
      "C": ("Capacitor_THT", "C_Disc_D5.0mm_W2.5mm_P5.00mm", 0),
      "LED": ("LED_THT", "LED_D5.0mm", 0),
      "V": ("Connector_PinHeader_2.54mm", "PinHeader_1x02_P2.54mm_Vertical", 90),
      "D": ("Diode_THT", "D_DO-35_SOD27_P7.62mm_Horizontal", 0), "Q": ("Package_TO_SOT_THT", "TO-92_Inline_Wide", 0),
      "M": ("Package_TO_SOT_THT", "TO-220-3_Vertical", 0), "QP": ("Package_TO_SOT_THT", "TO-92_Inline_Wide", 0), "MP": ("Package_TO_SOT_THT", "TO-220-3_Vertical", 0), "REG": ("Package_TO_SOT_THT", "TO-220-3_Vertical", 0), "L": ("Inductor_THT", "L_Axial_L11.0mm_D4.5mm_P15.24mm_Horizontal_Fastron_MECC", 0)}  # V = 2-pin supply header (assumption)
PAD = {"R": {"1": "1", "2": "2"}, "C": {"1": "1", "2": "2"}, "LED": {"k": "1", "a": "2"}, "V": {"p": "1", "n": "2"}, "D": {"k": "1", "a": "2"},
       "Q": {"b": "1", "c": "2", "e": "3"}, "M": {"g": "1", "s": "2", "d": "3"}, "L": {"1": "1", "2": "2"}, "QP": {"b": "1", "c": "2", "e": "3"}, "MP": {"g": "1", "s": "2", "d": "3"}, "REG": {"in": "1", "gnd": "2", "out": "3"}}
ROW_Y = 0.0


def mm(x, y): return VECTOR2I(FromMM(x), FromMM(y))


def main():
    spec = json.load(sys.stdin); out = spec["outdir"]; PITCH = float(spec.get("pitch", 25.0))
    b = pcbnew.BOARD(); nets = {}
    def net(n):
        if n not in nets:
            ni = pcbnew.NETINFO_ITEM(b, n); b.Add(ni); nets[n] = ni
        return nets[n]
    pads = {}  # net -> [(x, y)]
    missing = []; parts = []
    for i, c in enumerate(spec["components"]):
        lib, name, rot = FP[c["kind"]]
        fp = pcbnew.FootprintLoad(f"{LIB}/{lib}.pretty", name)
        if fp is None: missing.append(f"{lib}:{name}"); continue
        fp.SetReference(c["ref"]); fp.SetValue(c["value_text"])
        fp.SetPosition(mm(10 + i * PITCH, ROW_Y)); fp.SetOrientationDegrees(rot); b.Add(fp)
        bb = fp.GetBoundingBox(False, False)
        parts.append({"ref": c["ref"], "kind": c["kind"], "x": ToMM(bb.GetX() + bb.GetWidth() // 2), "y": ToMM(bb.GetY() + bb.GetHeight() // 2), "w": ToMM(bb.GetWidth()), "h": ToMM(bb.GetHeight())})
        for ours, num in PAD[c["kind"]].items():
            pad = fp.FindPadByNumber(num); n = c["pins"][ours]
            pad.SetNet(net(n)); p = pad.GetPosition(); pads.setdefault(n, []).append((ToMM(p.x), ToMM(p.y)))
    if missing: print(json.dumps({"error": f"footprints not found: {missing}"})); return
    names = sorted(nets)
    def seg(a, z, layer, n):
        t = pcbnew.PCB_TRACK(b); t.SetStart(mm(*a)); t.SetEnd(mm(*z)); t.SetWidth(FromMM(0.25)); t.SetLayer(layer); t.SetNet(nets[n]); b.Add(t)
    routed = []
    for k, n in enumerate(names):
        pts = pads[n]
        if len(pts) < 2: continue
        off = 6 + 1.5 * (k // 2); cy = ROW_Y - off if k % 2 == 0 else ROW_Y + off
        for (x, y) in pts:
            seg((x, y), (x, cy), pcbnew.F_Cu, n)
            v = pcbnew.PCB_VIA(b); v.SetPosition(mm(x, cy)); v.SetWidth(FromMM(0.8)); v.SetDrill(FromMM(0.4)); v.SetViaType(pcbnew.VIATYPE_THROUGH); v.SetNet(nets[n]); b.Add(v)
        xs = sorted(p[0] for p in pts)
        seg((xs[0], cy), (xs[-1], cy), pcbnew.B_Cu, n); routed.append(n)
    reach = 6 + 1.5 * math.ceil(len(names) / 2) + 4
    x0, x1 = 0.0, 10 + (len(spec["components"]) - 1) * PITCH + 14
    r = pcbnew.PCB_SHAPE(b); r.SetShape(pcbnew.SHAPE_T_RECT); r.SetStart(mm(x0, ROW_Y - reach)); r.SetEnd(mm(x1, ROW_Y + reach))
    r.SetLayer(pcbnew.Edge_Cuts); r.SetWidth(FromMM(0.1)); b.Add(r)
    path = f"{out}/design.kicad_pcb"
    pcbnew.SaveBoard(path, b)
    b2 = pcbnew.LoadBoard(path)  # reload from disk so DRC checks the saved file
    pcbnew.WriteDRCReport(b2, f"{out}/drc.rpt", pcbnew.EDA_UNITS_MILLIMETRES, True)
    print(json.dumps({"pcb": path, "routed_nets": routed, "board_mm": [round(x1 - x0, 1), round(2 * reach, 1)], "kicad": pcbnew.Version(),
                      "layout": {"board": {"x0": x0, "y0": ROW_Y - reach, "x1": x1, "y1": ROW_Y + reach}, "parts": parts, "pitch_mm": PITCH}}))


main()
