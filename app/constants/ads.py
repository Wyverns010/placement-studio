import re

# the standard ad buttons (what ad platforms offer); the writer picks one, it never invents a phrase
CTA_OPTIONS = ("Shop now", "Buy now", "Add to cart", "Order now", "Subscribe now", "Start subscription",
               "Get offer", "Book now", "Try it now", "Learn more")
NUMBER = re.compile(r"\$?\d[\d,.]*%?")  # a number in ad copy: "$40", "50%", "1,200"
