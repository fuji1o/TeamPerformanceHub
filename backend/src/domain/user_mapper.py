import json
import os

class UserMapper:
    def __init__(self, mapping_file: str = None):
        if mapping_file is None:
            mapping_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "author_mapping.json")
        
        try:
            with open(mapping_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.aliases = data.get("aliases", {})
        except FileNotFoundError:
            print(f"[WARN] Mapping file not found: {mapping_file}")
            self.aliases = {}
        except json.JSONDecodeError as e:
            print(f"[ERROR] Invalid JSON: {e}")
            self.aliases = {}
    
    def normalize_author(self, author_name: str) -> str:
        """Преобразует разные имена в единый username"""
        if not author_name:
            return author_name
        return self.aliases.get(author_name, author_name)