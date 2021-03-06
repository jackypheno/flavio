"""Functions for parsing the parameter data files"""

import yaml
import pkgutil
from flavio.classes import *
from flavio.statistics.probability import *
from flavio._parse_errors import errors_from_string
import flavio
import re
from flavio.measurements import _fix_correlation_matrix
from math import sqrt


def _read_yaml_object_metadata(obj, constraints):
    parameters = yaml.load(obj)
    for parameter_name, info in parameters.items():
        p = Parameter(parameter_name)
        if 'description' in info and info['description'] is not None:
            p.description = info['description']
        if 'tex' in info and info['tex'] is not None:
            p.tex = info['tex']

def read_file_metadata(filename, constraints):
    """Read parameter values from a YAML file."""
    with open(filename, 'r') as f:
        _read_yaml_object_metadata(f, constraints)

def _read_yaml_object_values(obj, constraints):
    parameters = yaml.load(obj)
    for parameter_name, value in parameters.items():
        p = Parameter[parameter_name] # this will raise an error if the parameter doesn't exist!
        constraints.set_constraint(parameter_name, value)

def _read_yaml_object_new(obj):
    """Read parameter constraints from a YAML stream or file that are compatible
    with the format generated by the `get_yaml` method of
    `flavio.classes.ParameterConstraints`."""
    parameters = yaml.load(obj)
    return ParameterConstraints.from_yaml_dict(parameters)

def _read_yaml_object_values_correlated(obj, constraints):
    list_ = yaml.load(obj)
    for parameter_group in list_:
        parameter_names = []
        central_values = []
        errors = []
        for dict_list in parameter_group['values']:
            parameter_name, value = list(dict_list.items())[0]
            Parameter[parameter_name] # this will raise an error if the parameter doesn't exist!
            parameter_names.append(parameter_name)
            error_dict = errors_from_string(value)
            central_values.append(error_dict['central_value'])
            squared_error = 0.
            for sym_err in error_dict['symmetric_errors']:
                squared_error += sym_err**2
            for asym_err in error_dict['asymmetric_errors']:
                squared_error += asym_err[0]*asym_err[1]
            errors.append(sqrt(squared_error))
        correlation = _fix_correlation_matrix(parameter_group['correlation'], len(parameter_names))
        covariance = np.outer(np.asarray(errors), np.asarray(errors))*correlation
        if not np.all(np.linalg.eigvals(covariance) > 0):
            # if the covariance matrix is not positive definite, try a dirty trick:
            # multiply all the correlations by 0.99.
            n_dim = len(correlation)
            correlation = (correlation - np.eye(n_dim))*0.99 + np.eye(n_dim)
            covariance = np.outer(np.asarray(errors), np.asarray(errors))*correlation
            # if it still isn't positive definite, give up.
            assert np.all(np.linalg.eigvals(covariance) > 0), "The covariance matrix is not positive definite!" + str(covariance)
        constraints.add_constraint(parameter_names, MultivariateNormalDistribution(central_values, covariance))

def read_file(filename):
    """Read parameter values from a YAML file in the format generated by the
    `get_yaml` method of the `ParameterConstraints` class, returning a
    `ParameterConstraints` instance."""
    with open(filename, 'r') as f:
        return _read_yaml_object_new(f)

def read_file_values(filename, constraints):
    """Read parameter values from a YAML file."""
    with open(filename, 'r') as f:
        _read_yaml_object_values(f, constraints)

def read_file_values_correlated(filename, constraints):
    """Read parameter values from a YAML file."""
    with open(filename, 'r') as f:
        _read_yaml_object_values_correlated(f, constraints)

def write_file(filename, constraints):
    """Write parameter constraints to a YAML file."""
    with open(filename, 'w') as f:
        yaml.dump(constraints.get_yaml_dict(), f)


# particles from the PDG data file whose mass we're interested in)
pdg_include = ['B(s)', 'B(c)', 'B(s)*', 'B*+', 'B*0', 'B+', 'B0', 'D(s)', 'D(s)*', 'D+', 'D0',
               'H', 'J/psi(1S)', 'K(L)', 'K(S)', 'K*(892)+', 'K*(892)0', 'K+', 'K0',
               'Lambda', 'Lambda(b)', 'Lambda(c)', 'omega(782)', 'D*(2007)', 'D*(2010)',
               'W', 'Z',  'b',  'c', 'd', 'e', 'eta', 'f(0)(980)',
               'mu',  'phi(1020)', 'pi+', 'pi0', 'psi(2S)', 'rho(770)+', 'rho(770)0',
               's', 't', 'tau', 'u']
# dictionary translating PDG particle names to the ones in the code.
pdg_translate = {
    'B(s)': 'Bs',
    'B(c)': 'Bc',
    'D(s)': 'Ds',
    'B(s)*': 'Bs*',
    'D(s)*': 'Ds*',
    'D*(2007)' : 'D*0',
    'D*(2010)' : 'D*+',
    'J/psi(1S)': 'J/psi',
    'K(L)': 'KL',
    'K(S)': 'KS',
    'K*(892)+': 'K*+',
    'K*(892)0': 'K*0',
    'phi(1020)': 'phi',
    'rho(770)0': 'rho0',
    'rho(770)+': 'rho+',
    'f(0)(980)': 'f0',
    "eta'(958)": "eta'",
    'omega(782)': 'omega',
    'Lambda(b)' : 'Lambdab',
    'Lambda(c)' : 'Lambdac',
    'Higgs' : 'h', # this is necessary for the 2013 data file
    'H' : 'h',
    }

def _read_pdg_masswidth(filename):
    """Read the PDG mass and width table and return a dictionary.

    Parameters
    ----------
    filname : string
        Path to the PDG data file, e.g. 'data/pdg/mass_width_2015.mcd'

    Returns
    -------
    particles : dict
        A dictionary where the keys are the particle names with the charge
        appended in case of a multiplet with different masses, e.g. 't'
        for the top quark, 'K+' and 'K0' for kaons.
        The value of the dictionary is again a dictionary with the following
        keys:
        - 'id': PDG particle ID
        - 'mass': list with the mass, postitive and negative error in GeV
        - 'width': list with the width, postitive and negative error in GeV
        - 'name': same as the key
    """
    data = pkgutil.get_data('flavio.physics', filename)
    lines = data.decode('utf-8').splitlines()
    particles_by_name = {}
    for line in lines:
        if  line.strip()[0] == '*':
            continue
        mass = ((line[33:51]), (line[52:60]), (line[61:69]))
        mass = [float(m) for m in mass]
        width = ((line[70:88]), (line[89:97]), (line[98:106]))
        if  width[0].strip() == '':
            width = (0,0,0)
        else:
            width = [float(w) for w in width]
        ids = line[0:32].split()
        charges = line[107:128].split()[1].split(',')
        if len(ids) != len(charges):
            raise ValueError()
        for i, id_ in enumerate(ids):
            particle = {}
            particle_charge = charges[i].strip()
            particle[particle_charge] = {}
            particle[particle_charge]['id'] = id_.strip()
            particle[particle_charge]['mass']  = mass
            particle[particle_charge]['charge']  = particle_charge
            particle[particle_charge]['width'] = width
            particle_name = line[107:128].split()[0]
            particle[particle_charge]['name'] = particle_name
            if particle_name in particles_by_name.keys():
                particles_by_name[particle_name].update(particle)
            else:
                particles_by_name[particle_name] = particle
    result = { k + kk: vv for k, v in particles_by_name.items() for kk, vv in v.items() if len(v) > 1}
    result.update({ k: list(v.values())[0] for k, v in particles_by_name.items() if len(v) == 1})
    return result

def _pdg_particle_string_to_tex(string):
    regex = re.compile(r"^([A-Za-z]+)([\*+-0]*)(?:\((\d*[A-Za-z]+)\))*(?:\((\d+)\))*([\*+-0]*)$")
    m = regex.match(string)
    if m is None:
        if string=='J/psi(1S)':
            return r'J/\psi'
        return string
    sup = m.group(2) + m.group(5)
    sub = m.group(3)
    out = m.group(1)
    if len(out) > 1:
        out = "\\" + out
    if sup is not None and sup != '':
        out += r'^{' + sup + r'}'
    if sub is not None and sub != '':
        out += r'_{' + sub + r'}'
    return out

def read_pdg(year, constraints):
    """Read particle masses and widths from the PDG data file of a given year."""
    particles = _read_pdg_masswidth('data/pdg/mass_width_' + str(year) + '.mcd')
    for particle in pdg_include:
        parameter_name = 'm_' + pdg_translate.get(particle, particle) # translate if necessary
        tex_name = _pdg_particle_string_to_tex(particle)
        try:
            # if parameter already exists, remove existing constraints on it
            m = Parameter[parameter_name]
            constraints.remove_constraint(parameter_name)
        except KeyError:
            # otherwise, create it
            m = Parameter(parameter_name)
        m.tex = r'$m_{' + tex_name + '}$'
        if tex_name =='b' or tex_name == 'c':
            m.tex = r'$m_{' + tex_name + '}(m_{' + tex_name + '})$'
            m.description = r'$' + tex_name + r'$ quark mass in the $\overline{\text{MS}}$ scheme at the scale $m_' + tex_name + r'$'
        elif tex_name =='s' or tex_name =='u' or tex_name =='d':
            m.tex = r'$m_{' + tex_name + r'}(2\,\text{GeV})$'
            m.description = r'$' + tex_name + r'$ quark mass in the $\overline{\text{MS}}$ scheme at 2 GeV'
        elif tex_name =='t':
            m.description = r'$' + tex_name + r'$ quark pole mass'
        else:
            m.description = r'$' + tex_name + r'$ mass'
        m_central, m_right, m_left = particles[particle]['mass']
        m_left = abs(m_left) # make left error positive
        if m_right == m_left:
            constraints.add_constraint([parameter_name],
                NormalDistribution(m_central, m_right))
        else:
            constraints.add_constraint([parameter_name],
                AsymmetricNormalDistribution(m_central,
                right_deviation=m_right, left_deviation=m_left))
        if particles[particle]['width'][0] == 0: # 0 is for particles where the width is unknown (e.g. B*)
            continue
        G_central, G_right, G_left = particles[particle]['width']
        G_left = abs(G_left) # make left error positive
        parameter_name = 'tau_' + pdg_translate.get(particle, particle) # translate if necessary
        try:
            # if parameter already exists, remove existing constraints on it
            tau = Parameter[parameter_name]
            constraints.remove_constraint(parameter_name)
        except KeyError:
            # otherwise, create it
            tau = Parameter(parameter_name)
        tau.tex = r'$\tau_{' + tex_name + '}$'
        tau.description = r'$' + tex_name + r'$ lifetime'
        tau_central = 1/G_central # life time = 1/width
        tau_left = G_left/G_central**2
        tau_right = G_right/G_central**2
        if tau_left == tau_right:
            constraints.add_constraint([parameter_name],
                NormalDistribution(tau_central, tau_right))
        else:
            constraints.add_constraint([parameter_name],
                AsymmetricNormalDistribution(tau_central,
                    right_deviation=tau_right, left_deviation=tau_left))



############### Read default parameters ###################

# Create the object
default_parameters = ParameterConstraints()

# Read the parameter metadata from the default YAML data file
_read_yaml_object_metadata(pkgutil.get_data('flavio', 'data/parameters_metadata.yml'), default_parameters)

# Read the uncorrelated parameter values from the default YAML data file
_read_yaml_object_values(pkgutil.get_data('flavio', 'data/parameters_uncorrelated.yml'), default_parameters)

# Read the correlated parameter values from the default YAML data file
_read_yaml_object_values_correlated(pkgutil.get_data('flavio', 'data/parameters_correlated.yml'), default_parameters)

# Read the parameters from the default PDG data file
read_pdg(2017, default_parameters)

# Read default parameters for B->V form factors
## first load LCSR-only form factors
flavio.physics.bdecays.formfactors.b_v.bsz_parameters.bsz_load_v2_lcsr(default_parameters)
## then load combined LCSR-lattice fits. Overwrites LCSR ones for B->K*, Bs->K*, Bs->phi, but not B->rho, B->omega
flavio.physics.bdecays.formfactors.b_v.bsz_parameters.bsz_load_v2_combined(default_parameters)

# Read default parameters for Lambdab->Lambda form factors
flavio.physics.bdecays.formfactors.lambdab_12.lattice_parameters.lattice_load_ho(default_parameters)
