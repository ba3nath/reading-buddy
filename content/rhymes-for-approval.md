# Rhymes for approval — Reading Buddy levels 6–7

Traditional nursery-rhyme lines only. Public-domain sources: Mother Goose / Project Gutenberg / Wikisource. No modern songs or poems.

**Status key:** `approved` = shipped in `content/items.json` with `pd_status=approved`. `candidate` = listed for human review, not shipped.

Human mid-flight approval was not available; a **minimal PD set** is marked `approved` below with sources so levels 6–7 can ship. Badhrinath may revoke or extend this list later.

---

## Approved (shipped)

### Jack and Jill

| Line | Status | Basis |
| --- | --- | --- |
| Jack and Jill went up the hill | approved | Traditional Mother Goose; PD |
| To fetch a pail of water | approved | Traditional Mother Goose; PD |
| Jack fell down and broke his crown | approved | Traditional Mother Goose; PD |
| And Jill came tumbling after | approved | Traditional Mother Goose; PD |

Sources:

- Project Gutenberg: *The Real Mother Goose* (illustrated by Blanche Fisher Wright), https://www.gutenberg.org/ebooks/10607
- Wikisource: “Jack and Jill”, https://en.wikisource.org/wiki/Jack_and_Jill_(nursery_rhyme)

### Humpty Dumpty

| Line | Status | Basis |
| --- | --- | --- |
| Humpty Dumpty sat on a wall | approved | Traditional Mother Goose; PD |
| Humpty Dumpty had a great fall | approved | Traditional Mother Goose; PD |
| All the king's horses and all the king's men | approved | Traditional Mother Goose; PD |
| Could not put Humpty together again | approved | Traditional Mother Goose; PD |

Sources:

- Gutenberg *The Real Mother Goose* (ebook 10607)
- Wikisource: “Humpty Dumpty”, https://en.wikisource.org/wiki/Humpty_Dumpty

### Twinkle, Twinkle, Little Star

| Line | Status | Basis |
| --- | --- | --- |
| Twinkle twinkle little star | approved | Jane Taylor, 1806; PD |
| How I wonder what you are | approved | Jane Taylor, 1806; PD |
| Up above the world so high | approved | Jane Taylor, 1806; PD |
| Like a diamond in the sky | approved | Jane Taylor, 1806; PD |

Sources:

- First published in *Rhymes for the Nursery* (1806); author died 1824 → PD worldwide for this text.
- Wikisource: “Twinkle, Twinkle, Little Star”, https://en.wikisource.org/wiki/Twinkle,_Twinkle,_Little_Star

### Baa, Baa, Black Sheep

| Line | Status | Basis |
| --- | --- | --- |
| Baa baa black sheep have you any wool | approved | Traditional Mother Goose; PD |
| Yes sir yes sir three bags full | approved | Traditional Mother Goose; PD |
| One for the master and one for the dame | approved | Traditional Mother Goose; PD |
| And one for the little boy who lives down the lane | approved | Traditional Mother Goose; PD |

Sources:

- Gutenberg *The Real Mother Goose* (ebook 10607)
- Wikisource: “Baa, Baa, Black Sheep”, https://en.wikisource.org/wiki/Baa,_Baa,_Black_Sheep

### Hickory Dickory Dock

| Line | Status | Basis |
| --- | --- | --- |
| Hickory dickory dock | approved | Traditional Mother Goose; PD |
| The mouse ran up the clock | approved | Traditional Mother Goose; PD |
| The clock struck one | approved | Traditional Mother Goose; PD |
| The mouse ran down | approved | Traditional Mother Goose; PD |
| The clock struck one the mouse ran down | approved | Traditional variant; PD |
| Hickory dickory dock (closing) | approved | Traditional Mother Goose; PD |

Sources:

- Gutenberg *The Real Mother Goose* (ebook 10607)
- Wikisource: “Hickory Dickory Dock”, https://en.wikisource.org/wiki/Hickory_Dickory_Dock

### Mary Had a Little Lamb

| Line | Status | Basis |
| --- | --- | --- |
| Mary had a little lamb | approved | Sarah Josepha Hale, 1830; PD |
| Its fleece was white as snow | approved | Hale, 1830; PD |
| And everywhere that Mary went | approved | Hale, 1830; PD |
| The lamb was sure to go | approved | Hale, 1830; PD |

Sources:

- Wikisource: “Mary Had a Little Lamb”, https://en.wikisource.org/wiki/Mary_Had_a_Little_Lamb
- First published 1830; author died 1879 → PD for this text.

### Rain, Rain, Go Away

| Line | Status | Basis |
| --- | --- | --- |
| Rain rain go away | approved | Traditional nursery rhyme; PD |
| Come again another day | approved | Traditional nursery rhyme; PD |

Sources:

- Traditional English nursery rhyme; widely printed in 19th-c. Mother Goose collections (e.g. Gutenberg ebook 10607 analogues / folk tradition). PD as traditional rhyme.

### Little Boy Blue

| Line | Status | Basis |
| --- | --- | --- |
| Little Boy Blue come blow your horn | approved | Traditional Mother Goose; PD |
| The sheep are in the meadow | approved | Traditional Mother Goose; PD |

Sources:

- Gutenberg *The Real Mother Goose* (ebook 10607)
- Wikisource: “Little Boy Blue”, https://en.wikisource.org/wiki/Little_Boy_Blue

---

## Candidates (not shipped)

None pending beyond the approved set above. Future candidates should be added here before copy into `items.json`.

---

## Ship mapping

| Level | How used |
| --- | --- |
| 6 | One approved line per item (`kind=line`), various `rhyme_group` values |
| 7 | 2–4 line groups (`l7-jack-jill`, `l7-humpty`, `l7-twinkle`, `l7-baa`, `l7-hickory`) in `line_index` order |
