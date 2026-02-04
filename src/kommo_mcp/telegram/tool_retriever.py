"""
RAG-based Tool Retriever for dynamic prompt generation.
Uses keyword matching and semantic similarity to find relevant tools.
"""

import os
import yaml
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class ToolRetriever:
    """Retrieves relevant tools based on user query."""
    
    def __init__(self, tools_dir: Optional[str] = None):
        """Initialize with tools directory path."""
        if tools_dir is None:
            tools_dir = Path(__file__).parent / 'tools'
        self.tools_dir = Path(tools_dir)
        self.tools: List[Dict[str, Any]] = []
        self._load_tools()
    
    def _load_tools(self):
        """Load all tool definitions from YAML files."""
        self.tools = []
        
        if not self.tools_dir.exists():
            logger.warning(f'Tools directory not found: {self.tools_dir}')
            return
        
        for yaml_file in self.tools_dir.glob('*.yaml'):
            try:
                with open(yaml_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Split by --- for multiple tools in one file
                docs = content.split('\n---\n')
                for doc in docs:
                    doc = doc.strip()
                    if not doc:
                        continue
                    tool = yaml.safe_load(doc)
                    if tool and 'name' in tool:
                        # Pre-compute lowercase keywords for matching
                        tool['_keywords_lower'] = [
                            kw.lower() for kw in tool.get('keywords', [])
                        ]
                        tool['_description_lower'] = tool.get('description', '').lower()
                        self.tools.append(tool)
                        
            except Exception as e:
                logger.error(f'Error loading {yaml_file}: {e}')
        
        logger.info(f'Loaded {len(self.tools)} tools from {self.tools_dir}')
    
    def _calculate_relevance(self, query: str, tool: Dict[str, Any]) -> float:
        """Calculate relevance score between query and tool."""
        query_lower = query.lower()
        query_words = set(query_lower.split())
        score = 0.0
        
        # Exact keyword match (highest weight)
        for keyword in tool['_keywords_lower']:
            if keyword in query_lower:
                score += 3.0
            # Partial word match
            elif any(keyword in word or word in keyword for word in query_words):
                score += 1.5
        
        # Tool name match
        tool_name = tool.get('name', '').lower()
        if tool_name in query_lower:
            score += 2.0
        
        # Category match
        category = tool.get('category', '').lower()
        if category in query_lower:
            score += 1.0
        
        # Description word overlap
        desc_words = set(tool['_description_lower'].split())
        overlap = len(query_words & desc_words)
        score += overlap * 0.3
        
        # Example query similarity
        for example in tool.get('examples', []):
            example_query = example.get('query', '').lower()
            example_words = set(example_query.split())
            example_overlap = len(query_words & example_words)
            if example_overlap >= 2:
                score += example_overlap * 0.5
        
        return score
    
    def retrieve(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Retrieve top-k most relevant tools for the query."""
        if not self.tools:
            return []
        
        # Calculate relevance scores
        scored_tools = []
        for tool in self.tools:
            score = self._calculate_relevance(query, tool)
            if score > 0:
                scored_tools.append((score, tool))
        
        # Sort by score descending
        scored_tools.sort(key=lambda x: x[0], reverse=True)
        
        # Return top-k tools
        result = [tool for score, tool in scored_tools[:top_k]]
        
        logger.debug(f'Query: "{query}" -> {len(result)} tools')
        for score, tool in scored_tools[:top_k]:
            logger.debug(f'  {tool["name"]}: {score:.2f}')
        
        return result
    
    def format_tools_for_prompt(self, tools: List[Dict[str, Any]]) -> str:
        """Format retrieved tools for inclusion in system prompt."""
        if not tools:
            return ''
        
        lines = ['📚 ДОСТУПНЫЕ ИНСТРУМЕНТЫ:']
        
        for tool in tools:
            name = tool.get('name', '')
            desc = tool.get('description', '').strip().split('\n')[0]
            
            lines.append(f'\n🔧 {name}')
            lines.append(f'   {desc}')
            
            # Add actions
            actions = tool.get('actions', [])
            if actions:
                if isinstance(actions[0], dict):
                    action_strs = [f"{k}: {v}" for a in actions for k, v in a.items()]
                else:
                    action_strs = actions
                lines.append(f'   Параметры: {", ".join(action_strs[:5])}')
            
            # Add example queries
            examples = tool.get('examples', [])[:2]
            if examples:
                example_strs = [ex.get('query', '') for ex in examples if ex.get('query')]
                if example_strs:
                    lines.append(f'   Примеры: "{example_strs[0]}"')
        
        return '\n'.join(lines)
    
    def get_tool_names(self, tools: List[Dict[str, Any]]) -> List[str]:
        """Get list of tool names from retrieved tools."""
        return [tool.get('name', '') for tool in tools]


# Base system prompt (compact)
BASE_SYSTEM_PROMPT = """Ты - AI-ассистент для управления CRM Kommo через Telegram.

ПРАВИЛА:
1. Используй ТОЛЬКО инструменты из списка ниже
2. Отвечай кратко и по делу
3. Форматируй ответы для Telegram: <b>жирный</b>, <code>ID</code>
4. Используй эмодзи: ✅❌📊📈💰👤🏢📋🔧⚡

"""


def build_dynamic_prompt(query: str, retriever: ToolRetriever, top_k: int = 5) -> str:
    """Build dynamic system prompt based on user query."""
    # Retrieve relevant tools
    relevant_tools = retriever.retrieve(query, top_k=top_k)
    
    # Format tools section
    tools_section = retriever.format_tools_for_prompt(relevant_tools)
    
    # Combine base prompt with tools
    return BASE_SYSTEM_PROMPT + tools_section


# Singleton instance
_retriever_instance: Optional[ToolRetriever] = None


def get_retriever() -> ToolRetriever:
    """Get or create singleton ToolRetriever instance."""
    global _retriever_instance
    if _retriever_instance is None:
        _retriever_instance = ToolRetriever()
    return _retriever_instance
