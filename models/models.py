from pydantic import BaseModel
from typing import List, Optional, Union

class WordEntry(BaseModel):
    word: str
    x: int
    y: int    
    direction: str   
    clue: str



class PuzzleCreateRequest(BaseModel):
    title: str
    topic: str
    level: int
    gridSize: int
    board: List[List[Optional[str]]]
    words: List[WordEntry]