# Validating the cost model ports against MATLAB

`src/adaptivestego/cost_models.py` contains Python ports of WOW and S-UNIWARD.
A port that is subtly wrong would invalidate every comparison built on it, so
it is checked numerically against the reference implementation published by the
Binghamton DDE Lab.

The check runs once, with MATLAB. Its output is committed, and from then on the
test suite re-runs the comparison against those stored maps on every commit,
with no MATLAB needed.

## Steps

1. **Get the reference code.** Download `WOW.m` and `S_UNIWARD.m` from
   <http://dde.binghamton.edu/download/stego_algorithms/> and put them in this
   directory (or anywhere on the MATLAB path).

2. **Expose the costs.** Both files finish their cost computation with

   ```matlab
   rhoP1(cover==255) = wetCost;
   rhoM1(cover==0)   = wetCost;
   ```

   Insert one line immediately after that pair, in each file:

   ```matlab
   assignin('base', 'ref_costs', {rhoP1, rhoM1});
   ```

   Nothing else changes; the functions still behave exactly as before. The
   modified files are not committed here, since they are not ours to
   redistribute.

3. **Write the test images** (once, from the repository root):

   ```bash
   python experiments/make_cost_vectors.py
   ```

4. **Dump the reference costs:**

   The driver adapts to whichever signature your copies declare. In the 2012
   and 2013 releases `WOW(cover, payload, params)` takes the **image matrix**
   and needs `params.p`, while `S_UNIWARD(coverPath, payload)` takes the
   **path** and hardcodes sigma. The driver passes each what it expects and
   checks with `nargin` whether to supply `params` at all.

   That distinction is not cosmetic: `WOW.m` starts with `double(cover)`, so
   handing it a path would quietly convert the file name into character codes
   and produce a 1-by-N cost map with no error raised. The driver therefore
   verifies that every cost map has the size of its image, and says which
   column of the `models` table to change if it does not.

   A failure *after* the costs are computed - almost always an STC MEX binary
   that was never compiled for your platform - is not a problem: the costs are
   published before any embedding starts, so the driver keeps them and prints a
   note.

   ```bash
   matlab -batch "run('matlab/dump_reference_costs.m')"
   ```

   This writes `tests/data/cost_vectors/<image>.<model>.<direction>.f64`,
   plain row-major float64 matrices.

5. **Compare:**

   ```bash
   python experiments/validate_costs.py
   ```

   It prints the largest relative difference per image, model and direction,
   and whether the maps of unusable ("wet") samples agree exactly. A faithful
   port lands around 1e-15; the default tolerance is 1e-9.

   The two files do not use the same wet cost - `WOW.m` uses 10^10 and
   `S_UNIWARD.m` uses 10^8 - and the port matches each of them, since a cost
   map only agrees value by value if the impossible directions agree too.

6. **Commit the reference files.** They are small - a 64x64 map is 32 KB - and
   they turn the one-off MATLAB check into a permanent regression test.

## What the comparison covers

The four test images are chosen to hit the parts of these models that are easy
to get wrong:

| Image | What it exercises |
|---|---|
| `smooth` | the ordinary case, gradients and texture |
| `saturated` | samples at 0 and at 255, so both wet directions appear |
| `edges` | hard edges next to perfectly flat areas, where the reciprocal Holder norm of WOW can divide by zero |
| `noisy` | a non-square image, which catches transposition and padding mistakes |

The usual causes of a mismatch, in rough order of likelihood: correlation used
where the reference convolves, `symmetric` padding replaced by `reflect`, the
one-pixel shift that the reference applies for even-sized filters, and the
row-major/column-major transposition when the binary files are read.
