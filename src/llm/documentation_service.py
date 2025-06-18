# """Documentation service that integrates LLM generation with database storage."""

# import logging
# from typing import List, Dict, Any
# from ..extraction.database_service import DatabaseService
# from .documentation_generator import DocumentationGenerator

# logger = logging.getLogger(__name__)


# class DocumentationService:
#     """Service to generate and store documentation for projects."""
    
#     def __init__(self, db_service: DatabaseService, doc_generator: DocumentationGenerator):
#         self.db = db_service
#         self.doc_generator = doc_generator
    
#     def generate_documentation_for_project(self, project_id: int) -> Dict[str, Any]:
#         """Generate documentation for all symbols in a project."""
#         # Get symbols that need documentation
#         symbols_to_document = self.db.get_symbols_without_documentation(project_id)
        
#         if not symbols_to_document:
#             logger.info("All symbols already have documentation")
#             return self.db.get_project_stats(project_id)
        
#         logger.info(f"Generating documentation for {len(symbols_to_document)} symbols...")
        
#         documented_count = 0
        
#         for symbol_data in symbols_to_document:
#             try:
#                 # Generate documentation using LLM
#                 documentation = self.doc_generator.generate_for_symbol_data(symbol_data)
                
#                 # Save to database
#                 self.db.update_symbol_documentation(symbol_data['id'], documentation)
                
#                 documented_count += 1
#                 logger.info(f"Documented {symbol_data['name']} ({documented_count}/{len(symbols_to_document)})")
                
#             except Exception as e:
#                 logger.error(f"Error documenting {symbol_data['name']}: {e}")
        
#         # Return final stats
#         final_stats = self.db.get_project_stats(project_id)
#         logger.info(f"Documentation complete: {final_stats['documentation_progress']:.1f}% done")
        
#         return final_stats