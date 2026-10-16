"""Pages made of blocks: a space's page, an app's home tab, and the Documentation
extension's pages all use this. ``sanitize`` cleans what the editor makes,
``render`` fills in the live parts for the reader, ``calc`` works out
calculations, ``blocks`` holds the blocks the slash menu offers, and
``references`` finds what pages use (so it isn't removed from under them).
"""
