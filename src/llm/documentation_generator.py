"""LLM-based documentation generator."""

from typing import List, Dict, Any
from ..extraction.models import SymbolModel

class DocumentationGenerator:
    """Generate documentation using LLM."""
    
    def __init__(self, llm_client):
        self.llm_client = llm_client
    
    def generate_documentation(self, symbols: List[SymbolModel]) -> List[SymbolModel]:
        """Generate documentation for a list of symbols."""
        for symbol in symbols:
            if symbol.symbol_type in ['method', 'function', 'class', 'constructor']:
                try:
                    doc_data = self._generate_single_documentation(symbol)
                    symbol.set_generated_documentation(doc_data)
                except Exception as e:
                    print(f"Error generating documentation for {symbol.name}: {e}")
        
        return symbols
    
    def _generate_single_documentation(self, symbol: SymbolModel) -> Dict[str, Any]:
        """Generate documentation for a single symbol."""
        context = symbol.get_llm_context()
        prompt = self._build_documentation_prompt(context)
        
        response = self.llm_client.generate(prompt)
        return self._parse_llm_response(response, context['language'])
    
    def _build_documentation_prompt(self, context: Dict[str, Any]) -> str:
        """Build prompt for LLM documentation generation."""
        language = context['language']
        doc_style = self._get_doc_style(language)
        
        prompt = f"""
Generate comprehensive documentation for this {language} {context['type']}:

**Symbol Name:** {context['name']}
**Type:** {context['type']}
**File:** {context['file_path']}

**Source Code:**
```{language}
{context['source_code']}
```

**Context Before:**
```{language}
{context['context_before']}
```

**Context After:**
```{language}
{context['context_after']}
```

**Existing Documentation:**
{context['existing_documentation'] or 'None'}

**LSP Hover Info:**
{context['hover_info'] or 'None'}

Please generate {doc_style} documentation including:
1. A clear, concise summary
2. All parameters with types and descriptions
3. Return value with type and description (if applicable)
4. Any exceptions/errors that might be thrown
5. Usage examples if helpful

Respond with a JSON object containing:
{{
  "summary": "Brief description",
  "parameters": [
    {{"name": "param1", "type": "String", "description": "Description of param1"}},
    {{"name": "param2", "type": "int", "description": "Description of param2"}}
  ],
  "returns": {{"type": "ReturnType", "description": "Description of return value"}},
  "throws": [
    {{"type": "ExceptionType", "description": "When this exception occurs"}}
  ],
  "examples": ["Usage example 1", "Usage example 2"],
  "since": "version if applicable",
  "deprecated": false,
  "deprecation_reason": ""
}}
"""
        return prompt
    
    def _get_doc_style(self, language: str) -> str:
        """Get documentation style for language."""
        styles = {
            'java': 'Javadoc',
            'javascript': 'JSDoc',
            'typescript': 'JSDoc', 
            'python': 'Sphinx/Google style',
            'go': 'Godoc',
            'csharp': 'XML documentation'
        }
        return styles.get(language, 'standard')
    
    def _parse_llm_response(self, response: str, language: str) -> Dict[str, Any]:
        """Parse LLM response into structured documentation data."""
        import json
        try:
            # Try to extract JSON from response
            if '```json' in response:
                start = response.find('```json') + 7
                end = response.find('```', start)
                json_str = response[start:end].strip()
            else:
                json_str = response.strip()
            
            return json.loads(json_str)
        except:
            # Fallback parsing
            return {
                'summary': 'Documentation generation failed',
                'parameters': [],
                'returns': {'type': '', 'description': ''},
                'throws': [],
                'examples': [],
                'since': '',
                'deprecated': False,
                'deprecation_reason': ''
            }