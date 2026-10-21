from src.schemas.base import COMMON_PARAMS, ParamSpec

SLAB_PARAMS = COMMON_PARAMS + [
    ParamSpec("slab_marks", "Slab panel marks", "Panel marks covered, e.g. S1-S6."),
    ParamSpec("slab_thickness", "Slab thickness", "Overall slab depth of the governing panel.", "mm"),
    ParamSpec("short_span", "Short span (lx)", "Clear/effective short span of the governing panel.", "mm"),
    ParamSpec("long_span", "Long span (ly)", "Clear/effective long span of the governing panel.", "mm"),
    ParamSpec("slab_type", "One-way / two-way", "Is the slab stated or detailed as one-way or two-way?"),
    ParamSpec("support_condition", "Support condition", "Simply supported / continuous / cantilever, edge conditions."),
    ParamSpec("main_bar_dia", "Main bar diameter", "Diameter of main (short-span) bars.", "mm"),
    ParamSpec("main_bar_spacing", "Main bar spacing", "Spacing of main bars.", "mm"),
    ParamSpec("dist_bar_dia", "Distribution bar diameter", "Diameter of distribution / long-span bars.", "mm"),
    ParamSpec("dist_bar_spacing", "Distribution bar spacing", "Spacing of distribution / long-span bars.", "mm"),
    ParamSpec("top_bars_support", "Top bars over supports", "Extra top (negative) reinforcement over supports and its extension (e.g. 0.3 lx)."),
    ParamSpec("cover_slab", "Clear cover - slab", "Clear cover to slab reinforcement.", "mm"),
    ParamSpec("torsion_reinforcement", "Corner torsion reinforcement", "Torsion mesh at discontinuous corners of two-way slabs.", required=False),
    ParamSpec("curtailment", "Curtailment / bent-up bars", "Alternate bars bent-up or curtailed and at what distance.", required=False),
    ParamSpec("cantilever_details", "Cantilever details", "Cantilever span, top bars and anchorage into back span.", required=False),
    ParamSpec("openings", "Openings / trimming bars", "Reinforcement around openings or cut-outs.", required=False),
    ParamSpec("sunken_slab", "Sunken / drop slab", "Sunken areas (toilets) and their detailing.", required=False),
    ParamSpec("live_load", "Live load", "Design imposed load if stated.", "kN/m2", required=False),
    ParamSpec("supporting_beams", "Supporting beams", "Beam marks / walls the panels rest on.", required=False),
    ParamSpec("chair_bars", "Chairs / spacers", "Chair bars or spacers to maintain top steel.", required=False),
]
