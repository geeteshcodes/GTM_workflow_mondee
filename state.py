"""
state.py
--------
Defines the GraphState TypedDict that flows through every node in the pipeline.
All nodes read from and write to this shared state object.
"""

from typing import TypedDict, List, Optional


class GraphState(TypedDict, total=False):
    """
    Shared state for the GTM UAE partner pipeline.

    Fields
    ------
    input_category : str
        The subcategory theme to search for, e.g. "Adventure & Extreme Sports".
        Set once at graph invocation time; read-only by all downstream nodes.

    run_id : str
        Unique ID for this pipeline run — used for log correlation.

    discovered_partners : list[dict]
        Records returned by the Discovery node.
        Each dict maps normalised column names to their values.

    enriched_partners : list[dict]
        Records produced by the Enrichment node.
        Same schema as discovered_partners, with contact fields filled in.

    outreach_results : list[dict]
        Records produced by the Outreach node.
        Each dict: {
            partner_name, call_sid, status, duration_s, summary, reason
        }
    """

    input_category:      str
    run_id:              str
    discovered_partners: List[dict]
    enriched_partners:   List[dict]
    outreach_results:    List[dict]