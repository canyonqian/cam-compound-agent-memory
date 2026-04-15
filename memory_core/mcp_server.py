"""
MCP Server — Standard Protocol for AI Tool Integration
=======================================================

Implements the Model Context Protocol (MCP) so that CAM's
Memory Core can be used by ANY MCP-compatible AI tool:

  - Claude Desktop
  - Cursor IDE  
  - VS Code with Copilot
  - Any MCP client

Tools exposed:
  1. remember      → Extract & store facts from conversation
  2. query_wiki    → Query accumulated knowledge
  3. wiki_status   → Get memory system statistics
  4. search        → Full-text search across Wiki pages
  5. list_pages    → List all Wiki pages
  6. read_page     → Read a specific Wiki page

Installation:
  Add to your MCP configuration (e.g., claude_desktop_config.json):
  {
    "mcpServers": {
      "cam-memory": {
        "command": "python",
        "args": ["-m", "memory_core.mcp_server"],
        "env": {
          "WIKI_PATH": "/path/to/your/wiki"
        }
      }
    }
  }

Then in any chat:
  User: "remember that I prefer TypeScript for frontend projects"
  AI: [calls remember tool] → Stored to Wiki automatically ✅

  User: "what do you know about my project architecture?"
  AI: [calls query_wiki tool] → [reads Wiki content] → Answers from memory ✅
"""

import asyncio
import json
import logging
import os
import sys
from typing import Any, Dict, List, Optional

logger = logging.getLogger("memory_core.mcp_server")


class MemoryMCPHandler:
    """
    MCP protocol handler for CAM Memory Core.
    
    Translates between MCP JSON-RPC and MemoryCore API calls.
    """
    
    def __init__(self, wiki_path: str = None):
        self.wiki_path = wiki_path or os.environ.get(
            "WIKI_PATH", "./wiki"
        )
        self.raw_path = os.environ.get("RAW_PATH", "./raw")
        
        # Lazy-initialized core
        self._core = None
    
    async def _get_core(self):
        """Get or initialize MemoryCore instance."""
        if self._core is None:
            from .agent_sdk import MemoryCore
            
            self._core = MemoryCore(
                wiki_path=self.wiki_path,
                raw_path=self.raw_path,
            )
            await self._core.initialize()
        
        return self._core
    
    async def handle_call(self, tool_name: str, arguments: Dict) -> Dict:
        """Handle an MCP tool call."""
        
        try:
            if tool_name == "remember":
                return await self._tool_remember(arguments)
            
            elif tool_name == "query_wiki":
                return await self._tool_query(arguments)
            
            elif tool_name == "wiki_status":
                return await self._tool_status(arguments)
            
            elif tool_name == "search":
                return await self._tool_search(arguments)
            
            elif tool_name == "list_pages":
                return await self._tool_list_pages(arguments)
            
            elif tool_name == "read_page":
                return await self._tool_read_page(arguments)
            
            else:
                return {
                    "success": False,
                    "error": f"Unknown tool: {tool_name}",
                    "available_tools": [
                        "remember", "query_wiki", "wiki_status",
                        "search", "list_pages", "read_page"
                    ],
                }
                
        except Exception as e:
            logger.error(f"MCP tool error [{tool_name}]: {e}")
            return {"success": False, "error": str(e)}
    
    # ============================================================
    # TOOL IMPLEMENTATIONS
    # ============================================================
    
    async def _tool_remember(self, args: Dict) -> Dict:
        """
        Tool: remember
        Extract and store knowledge from a conversation turn.
        
        Parameters (all optional, best effort extraction):
          user_message: What the human said
          assistant_response: What the AI responded
          force: Force extraction even if normally skipped
        
        Returns:
          Number of facts extracted and stored.
        """
        core = await self._get_core()
        
        user_msg = args.get("user_message", "")
        response = args.get("assistant_response", "")
        force = args.get("force", False)
        
        if not user_msg and not response:
            # If called without explicit messages, extract from context
            # This happens when AI calls it as a "side effect" tool
            user_msg = args.get("context", "")
            response = args.get("response", "")
        
        result = await core.remember(user_msg, response, force=force)
        
        return {
            "success": result.success,
            "facts_extracted": result.facts_extracted,
            "facts_written": result.facts_written,
            "processing_time_ms": result.processing_time_ms,
            "message": result.message,
        }
    
    async def _tool_query(self, args: Dict) -> Dict:
        """
        Tool: query_wiki
        Ask a question against accumulated knowledge.
        
        Parameters:
          question: The question to answer
        
        Returns:
          Answer synthesized from Wiki content.
        """
        core = await self._get_core()
        
        question = args.get("question", "")
        if not question:
            return {"success": False, "error": "Question is required"}
        
        answer = await core.query(question)
        
        return {
            "success": True,
            "question": question,
            "answer": answer,
        }
    
    async def _tool_status(self, args: Dict) -> Dict:
        """
        Tool: wiki_status
        Get comprehensive status of the memory system.
        
        Returns:
          Statistics about nodes, edges, extractions, storage size, etc.
        """
        core = await self._get_core()
        stats = await core.get_stats()
        
        return {
            "success": True,
            "status": "healthy" if stats.get("initialized") else "not_initialized",
            "stats": stats,
        }
    
    async def _tool_search(self, args: Dict) -> Dict:
        """
        Tool: search
        Search Wiki content for a query string.
        
        Parameters:
          query: Search terms
          limit: Max results (default 10)
        
        Returns:
          Matching pages with preview snippets.
        """
        core = await self._get_core()
        
        query = args.get("query", "")
        limit = args.get("limit", 10)
        
        if not query:
            return {"success": False, "error": "Query is required"}
        
        results = await core._shared_wiki.search_facts(query)
        
        return {
            "success": True,
            "query": query,
            "total_matches": len(results),
            "results": results[:limit],
        }
    
    async def _tool_list_pages(self, args: Dict) -> Dict:
        """
        Tool: list_pages
        List all pages in the Wiki.
        
        Parameters:
          directory: Filter by subdirectory (concept/entity/synthesis)
        
        Returns:
          List of page metadata.
        """
        core = await self._get_core()
        
        directory = args.get("directory")
        pages = await core._shared_wiki.list_pages(subdirectory=directory)
        
        return {
            "success": True,
            "total_pages": len(pages),
            "pages": pages,
        }
    
    async def _tool_read_page(self, args: Dict) -> Dict:
        """
        Tool: read_page
        Read a specific Wiki page.
        
        Parameters:
          path: Relative path to the page (e.g., "concept/redis.md")
        
        Returns:
          Page content as Markdown.
        """
        core = await self._get_core()
        
        path = args.get("path", "")
        if not path:
            return {"success": False, "error": "Path is required"}
        
        content = await core._shared_wiki.read_page(path)
        
        if content is None:
            return {"success": False, "error": f"Page not found: {path}"}
        
        return {
            "success": True,
            "path": path,
            "content": content,
            "length": len(content),
        }


# ============================================================
# MCP PROTOCOL SERVER (stdio transport)
# ============================================================

async def run_mcp_server_stdio():
    """
    Run the MCP server over stdin/stdout (JSON-RPC).
    
    This is the standard way MCP servers communicate with clients.
    Each line on stdin is a JSON-RPC request; each line on stdout
    is a JSON-RPC response.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    
    handler = MemoryMCPHandler()
    
    logger.info("CAM MCP Server starting (stdio mode)")
    logger.info(f"Wiki path: {handler.wiki_path}")
    
    # Process requests from stdin line by line
    import asyncio
    
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    
    # Use stdin/stdout directly for JSON-RPC
    import sys
    
    while True:
        try:
            line = await loop.run_in_executor(None, sys.stdin.readline)
            
            if not line:
                break
            
            line = line.strip()
            if not line:
                continue
            
            # Parse JSON-RPC request
            request = json.loads(line)
            
            # Handle request
            method = request.get("method", "")
            params = request.get("params", {})
            req_id = request.get("id")
            
            logger.debug(f"Request: {method} id={req_id}")
            
            if method == "tools/list":
                # Return available tools
                response = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "tools": [
                            {
                                "name": "remember",
                                "description": (
                                    "Extract and store knowledge from "
                                    "conversation into the Wiki. Call this "
                                    "after meaningful exchanges where the "
                                    "user shares preferences, decisions, "
                                    "facts, or context."
                                ),
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "user_message": {
                                            "type": "string",
                                            "description": (
                                                "What the user said"
                                            ),
                                        },
                                        "assistant_response": {
                                            "type": "string",
                                            "description": (
                                                "What the AI responded"
                                            ),
                                        },
                                        "force": {
                                            "type": "boolean",
                                            "description": (
                                                "Force extraction"
                                            ),
                                        },
                                    },
                                },
                            },
                            {
                                "name": "query_wiki",
                                "description": (
                                    "Query the accumulated knowledge base "
                                    "to retrieve information about past "
                                    "conversations, decisions, preferences."
                                ),
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "question": {
                                            "type": "string",
                                            "description": "Question to ask",
                                        },
                                    },
                                    "required": ["question"],
                                },
                            },
                            {
                                "name": "wiki_status",
                                "description": (
                                    "Get statistics and health status of "
                                    "the memory/Wiki system."
                                ),
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {},
                                },
                            },
                            {
                                "name": "search",
                                "description": (
                                    "Full-text search across all Wiki "
                                    "pages for specific terms or topics."
                                ),
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "query": {
                                            "type": "string",
                                            "description": "Search terms",
                                        },
                                        "limit": {
                                            "type": "integer",
                                            "description": "Max results",
                                            "default": 10,
                                        },
                                    },
                                    "required": ["query"],
                                },
                            },
                            {
                                "name": "list_pages",
                                "description": (
                                    "List all Wiki pages, optionally "
                                    "filtered by category."
                                ),
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "directory": {
                                            "type": "string",
                                            "description": (
                                                "Filter: concept|entity|synthesis"
                                            ),
                                        },
                                    },
                                },
                            },
                            {
                                "name": "read_page",
                                "description": (
                                    "Read the full content of a specific "
                                    "Wiki page."
                                ),
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "path": {
                                            "type": "string",
                                            "description": (
                                                "Page relative path, e.g. "
                                                "'concept/redis.md'"
                                            ),
                                        },
                                    },
                                    "required": ["path"],
                                },
                            },
                        ],
                    },
                }
                
            elif method == "tools/call":
                # Execute a tool call
                tool_name = params.get("name", "")
                tool_args = params.get("arguments", {})
                
                result = await handler.handle_call(tool_name, tool_args)
                
                response = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(result, indent=2, 
                                                    ensure_ascii=False),
                            }
                        ],
                        "isError": not result.get("success", True),
                    },
                }
                
            elif method == "initialize":
                response = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "serverInfo": {
                            "name": "cam-memory-core",
                            "version": "2.0.0",
                        },
                    },
                }
                
            elif method == "notifications/initialized":
                # Client ready, no response needed
                continue
                
            else:
                response = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32601,
                        "message": f"Method not found: {method}",
                    },
                }
            
            # Write response to stdout
            output = json.dumps(response, ensure_ascii=False)
            print(output, flush=True)
            
        except json.JSONDecodeError as e:
            error_resp = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {e}"},
            }
            print(json.dumps(error_resp), flush=True)
            
        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error(f"Unhandled error: {e}", exc_info=True)
            error_resp = {
                "jsonrpc": "2.0",
                "id": req_id if 'req_id' in dir() else None,
                "error": {"code": -32603, "message": f"Internal error: {e}"},
            }
            print(json.dumps(error_resp), flush=True)
    
    logger.info("MCP Server shutting down")


def main():
    """Entry point for `python -m memory_core.mcp_server`."""
    import asyncio
    asyncio.run(run_mcp_server_stdio())


if __name__ == "__main__":
    main()
