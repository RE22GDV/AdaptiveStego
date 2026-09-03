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
%       matlab -batch "run('matlab/dump_reference_costs.m')"
%
% 4. Back in Python:
%
%       python experiments/validate_costs.py
%
% Note on the embedding stage: the costs are published before any embedding
% happens, so if the reference function later fails - a missing MEX binary is
% the usual reason - this script still gets what it came for and says so.
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

% The reference defaults: p = -1 for WOW, sigma = 1 for S-UNIWARD.
models = { ...
    'wow',     'WOW',       struct('p', -1); ...
    'uniward', 'S_UNIWARD', struct('sigma', 1) ...
};
payload = 0.4;      % the value does not affect the costs, only the simulator

fprintf('writing reference costs for %d images\n', numel(images));

for iImage = 1:numel(images)
    imagePath = fullfile(vectorDir, images(iImage).name);
    [~, stem]  = fileparts(images(iImage).name);

    for iModel = 1:size(models, 1)
        model      = models{iModel, 1};
        entry      = models{iModel, 2};
        params     = models{iModel, 3};

        evalin('base', 'clear ref_costs');
        callReference(entry, imagePath, payload, params, model);

        if evalin('base', 'exist(''ref_costs'', ''var'')') ~= 1
            error(['%s did not publish its costs. Add the assignin line ' ...
                   'described in the header of this file.'], entry);
        end
        costs = evalin('base', 'ref_costs');
        rhoP1 = costs{1};
        rhoM1 = costs{2};

        writeMatrix(fullfile(vectorDir, sprintf('%s.%s.up.f64', stem, model)), ...
                    rhoP1);
        writeMatrix(fullfile(vectorDir, sprintf('%s.%s.down.f64', stem, model)), ...
                    rhoM1);

        live = rhoP1(rhoP1 < 1e10);
        fprintf('  %-10s %-8s %dx%d  range [%.6g, %.6g]\n', stem, model, ...
                size(rhoP1, 1), size(rhoP1, 2), min(live), max(live));
    end
end

fprintf('done. Now run: python experiments/validate_costs.py\n');


function callReference(entry, imagePath, payload, params, model)
    % Call the reference implementation, adapting to its signature.
    %
    % Different releases declare either (cover, payload) or
    % (cover, payload, params). nargin on the file name tells us which,
    % and a negative value means varargin, in which case params is passed.
    declared = nargin(entry);
    handle   = str2func(entry);

    try
        if declared >= 3 || declared < 0
            handle(imagePath, payload, params);
        else
            handle(imagePath, payload);
        end
    catch err
        % The costs are assigned before embedding begins, so an error raised
        % later - typically a MEX file that was never compiled for this
        % platform - still leaves us with what we need.
        if evalin('base', 'exist(''ref_costs'', ''var'')') == 1
            fprintf(['    %s stopped after computing the costs (%s); ' ...
                     'the costs themselves are fine\n'], model, err.message);
            return;
        end

        if strcontains(err.message, 'Too many input arguments')
            handle(imagePath, payload);
            return;
        end
        if strcontains(err.message, 'Not enough input arguments')
            error(['%s wants a params field this script does not supply. ' ...
                   'The error above names the line; add that field to the ' ...
                   'models table near the top of this file.'], entry);
        end
        rethrow(err);
    end
end


function tf = strcontains(text, pattern)
    % contains() is not available in older MATLAB releases.
    tf = ~isempty(strfind(text, pattern)); %#ok<STREMP>
end


function writeMatrix(path, matrix)
    fid = fopen(path, 'w');
    if fid < 0
        error('cannot write %s', path);
    end
    % Transposed, because MATLAB writes column-major and numpy reads row-major.
    fwrite(fid, matrix', 'double');
    fclose(fid);
end
