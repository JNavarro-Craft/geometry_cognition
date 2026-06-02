"""sap_bridge — read-only HTTP service over the SAP2000 OAPI.

The single integration point with SAP2000 (Objetivo 1). Consumers talk HTTP; nobody
embeds the SAP DLL. Strictly agnostic: exposes facts, interprets no structural domain.
"""
