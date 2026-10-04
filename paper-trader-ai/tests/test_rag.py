from trader.rag import KnowledgeBase, chunk_text


def test_chunking_respects_limit():
    text = "\n\n".join(f"Paragraph {i}. " + "word " * 80 for i in range(20))
    chunks = chunk_text(text, max_chars=600, overlap=100)
    assert len(chunks) > 1 and all(len(c) <= 700 for c in chunks)


def test_search_with_filters():
    kb = KnowledgeBase(collection="test_kb")
    kb.add_document("Covered calls cap upside in exchange for premium.", "strategy", "cc", "Covered calls")
    kb.add_document("Sold AAPL 200 call, shares got called away.", "journal", "t1", "Trade 1", symbol="AAPL")
    kb.add_document("Sold MSFT 400 put for income.", "journal", "t2", "Trade 2", symbol="MSFT")
    hits = kb.search("called away", sources=["journal"], symbol="AAPL")
    assert [h.title for h in hits] == ["Trade 1"]
    # Re-adding the same key replaces instead of duplicating.
    kb.add_document("Updated note.", "journal", "t1", "Trade 1", symbol="AAPL")
    assert kb.stats()["journal"] == 2
