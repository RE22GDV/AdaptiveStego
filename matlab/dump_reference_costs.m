% Dump the reference embedding costs of WOW and S-UNIWARD.
%
% This writes the cost maps that the Python port in
% src/adaptivestego/cost_models.py is validated against. Run it once; the
% output is committed, and after that the comparison runs in CI with no
% MATLAB involved.
%
% ---------------------------------------------------------------------------
% Setup
% ---------------------------------------------------------------------------
% 1. Download WOW.m and S_UNIWARD.m from the Binghamton DDE Lab:
%       http://dde.binghamton.edu/download/stego_algorithms/
%    Put them next to this file, or anywhere on the MATLAB path.
%
% 2. Add ONE line to each of them, so the costs can be read out. Both files
%    end their cost computation with these two lines:
%
%       rhoP1(cover==255) = wetCost;
%       rhoM1(cover==0)   = wetCost;
%
%    Immediately after that pair, insert:
%
%       assignin('base', 'ref_costs', {rhoP1, rhoM1});
%
%    Nothing else changes: the functions still do exactly what they did.
%
% 3. Run this script from the repository root:
%
%       cd D:/path/to/AdaptiveStego
%       run('matlab/dump_reference_costs.m')
%
% 4. Back in Python:
%
%       python experiments/validate_costs.py
%
% ---------------------------------------------------------------------------

clear ref_costs;

repoRoot   = fileparts(fileparts(mfilename('fullpath')));
vectorDir  = fullfile(repoRoot, 'tests', 'data', 'cost_vectors');
addpath(fileparts(mfilename('fullpath')));

if exist('WOW', 'file') ~= 2 || exist('S_UNIWARD', 'file') ~= 2
    error(['WOW.m and S_UNIWARD.m were not found. Download them from the ' ...
           'DDE Lab and put them on the MATLAB path (see the header of ' ...
           'this file).']);
end

images = dir(fullfile(vectorDir, '*.pgm'));
if isempty(images)
    error('No test vectors in %s. Run experiments/make_cost_vectors.py first.', ...
          vectorDir);
end

models  = {'wow', 'uniward'};
payload = 0.4;      % the value does not affect the costs, only the simulator

fprintf('writing reference costs for %d images\n', numel(images));

for iImage = 1:numel(images)
    imagePath = fullfile(vectorDir, images(iImage).name);
    [~, stem]  = fileparts(images(iImage).name);

    for iModel = 1:numel(models)
        model = models{iModel};

        clear ref_costs;
        switch model
            case 'wow'
                WOW(imagePath, payload);
            case 'uniward'
                S_UNIWARD(imagePath, payload);
        end

        if evalin('base', 'exist(''ref_costs'', ''var'')') ~= 1
            error(['%s did not publish its costs. Add the assignin line ' ...
                   'described in the header of this file.'], model);
        end
        costs = evalin('base', 'ref_costs');
        rhoP1 = costs{1};
        rhoM1 = costs{2};

        % Row-major float64, so numpy can read it with a plain fromfile.
        writeMatrix(fullfile(vectorDir, sprintf('%s.%s.up.f64', stem, model)), ...
                    rhoP1);
        writeMatrix(fullfile(vectorDir, sprintf('%s.%s.down.f64', stem, model)), ...
                    rhoM1);

        fprintf('  %-10s %-8s %dx%d  range [%.6g, %.6g]\n', stem, model, ...
                size(rhoP1, 1), size(rhoP1, 2), ...
                min(rhoP1(:)), max(rhoP1(rhoP1 < 1e10)));
    end
end

fprintf('done. Now run: python experiments/validate_costs.py\n');


function writeMatrix(path, matrix)
    fid = fopen(path, 'w');
    if fid < 0
        error('cannot write %s', path);
    end
    % Transposed, because MATLAB writes column-major and numpy reads row-major.
    fwrite(fid, matrix', 'double');
    fclose(fid);
end
