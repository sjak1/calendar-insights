"""
Markdown formatting utilities.
"""
import json


def format_response_as_markdown(response_text: str, input_list: list) -> str:
    """
    Format the response text as markdown, enhancing it with tables from SQL results.
    """
    formatted = response_text
    
    # Look for SQL query results in the input_list and format them as tables
    for item in input_list:
        # Handle both dict and Pydantic model objects
        if hasattr(item, 'model_dump'):
            # Pydantic model - convert to dict
            item_dict = item.model_dump()
        elif isinstance(item, dict):
            # Already a dict
            item_dict = item
        else:
            # Skip if we can't convert
            continue
        
        if item_dict.get("type") == "function_call_output" and "output" in item_dict:
            try:
                output_data = json.loads(item_dict["output"])
                if "query_database" in output_data:
                    db_result = output_data["query_database"]
                    if isinstance(db_result, dict) and "rows" in db_result and db_result["rows"]:
                        rows = db_result["rows"]
                        columns = db_result.get("columns", [])
                        
                        if rows and columns:
                            # Create markdown table
                            table_lines = []
                            # Header
                            table_lines.append("| " + " | ".join(columns) + " |")
                            table_lines.append("| " + " | ".join(["---"] * len(columns)) + " |")
                            # Rows (limit to 50 rows for readability)
                            for row in rows[:50]:
                                row_values = []
                                for col in columns:
                                    value = row.get(col, "")
                                    # Convert to string and escape pipe characters
                                    value_str = str(value) if value is not None else ""
                                    value_str = value_str.replace("|", "\\|").replace("\n", " ")
                                    # Truncate long values
                                    if len(value_str) > 100:
                                        value_str = value_str[:97] + "..."
                                    row_values.append(value_str)
                                table_lines.append("| " + " | ".join(row_values) + " |")
                            
                            if len(rows) > 50:
                                table_lines.append(f"\n*Showing 50 of {len(rows)} rows*")
                            
                            table_md = "\n".join(table_lines)
                            
                            # Insert table after the response if it's not already there
                            if table_md not in formatted:
                                formatted += f"\n\n### Query Results\n\n{table_md}"
            except (json.JSONDecodeError, KeyError, TypeError):
                # Skip if we can't parse the output
                continue
    
    return formatted
