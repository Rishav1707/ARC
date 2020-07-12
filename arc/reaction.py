"""
A module for representing a reaction.
"""

from typing import List, Optional

from qcelemental.exceptions import ValidationError
from qcelemental.models.molecule import Molecule as QCMolecule

from rmgpy.reaction import Reaction
from rmgpy.species import Species

import arc.rmgdb as rmgdb
from arc.common import extermum_list, get_logger
from arc.exceptions import ReactionError, InputError
from arc.settings import default_ts_methods
from arc.species.converter import xyz_to_str
from arc.species.species import ARCSpecies, check_atom_balance


logger = get_logger()


class ARCReaction(object):
    """
    A class for representing a chemical reaction.

    Either give reactants and products (just list of labels corresponding to :ref:`ARCSpecies <species>`),
    a reaction label, or an RMG Reaction object.
    If the reactants and products in the RMG Reaction aren't ARCSpecies, they will be created.

    The ARCReaction object stores the labels corresponding to the reactants, products and TS ARCSpecies objects
    as self.reactants, self.products, and self.ts_label, respectively.

    Args:
        label (str, optional): The reaction's label in the format `r1 + r2 <=> p1 + p2`
                               (or unimolecular on either side, as appropriate).
        reactants (list, optional): A list of reactants labels corresponding to an :ref:`ARCSpecies <species>`.
        products (list, optional): A list of products labels corresponding to an :ref:`ARCSpecies <species>`.
        ts_label (str, optional): The :ref:`ARCSpecies <species>` label of the respective TS.
        rmg_reaction (Reaction, optional): An RMG Reaction class.
        ts_methods (list, optional): Methods to try for generating TS guesses. If an ARCSpecies is a TS and ts_methods
                                     is empty (passing an empty list), then xyz (user guess) must be given.
        ts_xyz_guess (list, optional): A list of TS XYZ user guesses, each in a string format.
        multiplicity (int, optional): The reaction surface multiplicity. A trivial guess will be made unless provided.
        charge (int, optional): The reaction surface charge.
        reaction_dict (dict, optional): A dictionary to create this object from (used when restarting ARC).
        preserve_param_in_scan (list, optional): Entries are length two iterables of atom indices (1-indexed)
                                                 between which distances and dihedrals of these pivots must be
                                                 preserved. Used for identification of rotors which break a TS.

    Attributes:
        label (str): The reaction's label in the format `r1 + r2 <=> p1 + p2`
                     (or unimolecular on either side, as appropriate).
        family (str): The RMG kinetic family, if applicable.
        family_own_reverse (bool): Whether the RMG family is its own reverse.
        reactants (list): A list of reactants labels corresponding to an :ref:`ARCSpecies <species>`.
        products (list): A list of products labels corresponding to an :ref:`ARCSpecies <species>`.
        r_species (list): A list of reactants :ref:`ARCSpecies <species>` objects.
        p_species (list): A list of products :ref:`ARCSpecies <species>` objects.
        ts_species (ARCSpecies): The :ref:`ARCSpecies <species>` corresponding to the reaction's TS.
        dh_rxn298 (float):  The heat of reaction at 298K.
        kinetics (Arrhenius): The high pressure limit rate coefficient calculated by ARC.
        rmg_kinetics (Arrhenius): The kinetics generated by RMG, for reality-check.
        rmg_reaction (Reaction): An RMG Reaction class.
        rmg_reactions (list): A list of RMG Reaction objects with RMG rates for comparisons.
        long_kinetic_description (str): A description for the species entry in the thermo library outputted.
        ts_methods (list): Methods to try for generating TS guesses. If an ARCSpecies is a TS and ts_methods
                           is empty (passing an empty list), then xyz (user guess) must be given.
        ts_xyz_guess (list): A list of TS XYZ user guesses, each in a string format.
        multiplicity (int): The reaction surface multiplicity. A trivial guess will be made unless provided.
        charge (int): The reaction surface charge.
        index (int): An auto-generated index associating the ARCReaction object with the
                     corresponding TS :ref:`ARCSpecies <species>` object.
        ts_label (str): The :ref:`ARCSpecies <species>` label of the respective TS.
        preserve_param_in_scan (list): Entries are length two iterables of atom indices (1-indexed) between which
                                       distances and dihedrals of these pivots must be preserved.
        _atom_map (List[int]): An atom map, mapping the reactant atoms to the product atoms.
        I.e., an atom map of [0, 2, 1] means that reactant atom 0 matches product atom 0,
        reactant atom 1 matches product atom 2, and reactant atom 2 matches product atom 1.
    """
    def __init__(self,
                 label: str = '',
                 reactants: Optional[List[str]] = None,
                 products: Optional[List[str]] = None,
                 ts_label: Optional[str] = None,
                 rmg_reaction: Optional[Reaction] = None,
                 ts_methods: Optional[List[str]] = None,
                 ts_xyz_guess: Optional[list] = None,
                 multiplicity: Optional[int] = None,
                 charge: int = 0,
                 reaction_dict: Optional[dict] = None,
                 preserve_param_in_scan: Optional[list] = None,
                 ):
        self.arrow = ' <=> '
        self.plus = ' + '
        self.r_species = list()
        self.p_species = list()
        self.kinetics = None
        self.rmg_kinetics = None
        self.long_kinetic_description = ''
        self.family = None
        self.family_own_reverse = 0
        self.ts_label = ts_label
        self.dh_rxn298 = None
        self.rmg_reactions = None
        self.ts_xyz_guess = ts_xyz_guess or list()
        self.preserve_param_in_scan = preserve_param_in_scan
        if reaction_dict is not None:
            # Reading from a dictionary
            self.from_dict(reaction_dict=reaction_dict)
        else:
            # Not reading from a dictionary
            self.label = label
            self.index = None
            self.ts_species = None
            self.multiplicity = multiplicity
            self.charge = charge
            if self.multiplicity is not None and not isinstance(self.multiplicity, int):
                raise InputError('Reaction multiplicity must be an integer, got {0} of type {1}.'.format(
                    self.multiplicity, type(self.multiplicity)))
            self.reactants = reactants
            self.products = products
            self.rmg_reaction = rmg_reaction
            if self.rmg_reaction is None and (self.reactants is None or self.products is None) and not self.label:
                raise InputError('Cannot determine reactants and/or products labels for reaction {0}'.format(
                    self.label))
            self.set_label_reactants_products()
            self.ts_methods = ts_methods if ts_methods is not None else default_ts_methods
            self.ts_methods = [tsm.lower() for tsm in self.ts_methods]
            self.ts_xyz_guess = ts_xyz_guess if ts_xyz_guess is not None else list()
            self._atom_map = None
        if len(self.reactants) > 3 or len(self.products) > 3:
            raise ReactionError(f'An ARC Reaction can have up to three reactants / products. got {len(self.reactants)} '
                                f'reactants and {len(self.products)} products for reaction {self.label}.')
        if self.ts_xyz_guess is not None and not isinstance(self.ts_xyz_guess, list):
            self.ts_xyz_guess = [self.ts_xyz_guess]
        self.check_atom_balance()

    @property
    def atom_map(self):
        """The reactants to products atom map"""
        if self._atom_map is None \
                and all(species.get_xyz(generate=False) is not None for species in self.r_species + self.p_species):
            self._atom_map = self.get_atom_map()
        return self._atom_map

    @atom_map.setter
    def atom_map(self, value):
        """Allow setting the atom map"""
        self._atom_map = value

    def __str__(self) -> str:
        """Return a string representation of the object"""
        str_representation = f'ARCReaction('
        str_representation += f'label="{self.label}", '
        str_representation += f'rmg_reaction="{self.rmg_reaction}", '
        if self.preserve_param_in_scan is not None:
            str_representation += f'preserve_param_in_scan="{self.preserve_param_in_scan}", '
        str_representation += f'multiplicity={self.multiplicity}, '
        str_representation += f'charge={self.charge})'
        return str_representation

    def as_dict(self) -> dict:
        """A helper function for dumping this object as a dictionary in a YAML file for restarting ARC"""
        reaction_dict = dict()
        reaction_dict['label'] = self.label
        reaction_dict['index'] = self.index
        reaction_dict['multiplicity'] = self.multiplicity
        reaction_dict['charge'] = self.charge
        reaction_dict['reactants'] = self.reactants
        reaction_dict['products'] = self.products
        reaction_dict['r_species'] = [spc.as_dict() for spc in self.r_species]
        reaction_dict['p_species'] = [spc.as_dict() for spc in self.p_species]
        if self.ts_species is not None:
            reaction_dict['ts_species'] = self.ts_species.as_dict()
        if self._atom_map is not None:
            reaction_dict['atom_map'] = self._atom_map
        if self.preserve_param_in_scan is not None:
            reaction_dict['preserve_param_in_scan'] = self.preserve_param_in_scan
        if 'rmg_reaction' in reaction_dict:
            reaction_dict['rmg_reaction'] = self.rmg_reaction_to_str()
        reaction_dict['family'] = self.family
        reaction_dict['family_own_reverse'] = self.family_own_reverse
        reaction_dict['long_kinetic_description'] = self.long_kinetic_description
        reaction_dict['label'] = self.label
        reaction_dict['ts_methods'] = self.ts_methods
        reaction_dict['ts_xyz_guess'] = self.ts_xyz_guess
        reaction_dict['ts_label'] = self.ts_label
        return reaction_dict

    def from_dict(self, reaction_dict: dict):
        """
        A helper function for loading this object from a dictionary in a YAML file for restarting ARC.
        """
        self.index = reaction_dict['index'] if 'index' in reaction_dict else None
        self.label = reaction_dict['label'] if 'label' in reaction_dict else ''
        self.multiplicity = reaction_dict['multiplicity'] if 'multiplicity' in reaction_dict else None
        self.charge = reaction_dict['charge'] if 'charge' in reaction_dict else 0
        self.reactants = reaction_dict['reactants'] if 'reactants' in reaction_dict else None
        self.products = reaction_dict['products'] if 'products' in reaction_dict else None
        self.family = reaction_dict['family'] if 'family' in reaction_dict else None
        self.family_own_reverse = reaction_dict['family_own_reverse'] if 'family_own_reverse' in reaction_dict else 0
        if 'rmg_reaction' in reaction_dict:
            self.rmg_reaction_from_str(reaction_string=reaction_dict['rmg_reaction'])
        else:
            self.rmg_reaction = None
        self.set_label_reactants_products()
        if self.rmg_reaction is None and (self.reactants is None or self.products is None):
            raise InputError(f'Cannot determine reactants and/or products labels for reaction {self.label}')
        if self.reactants is None or self.products is None:
            if not all([spc.label for spc in self.rmg_reaction.reactants + self.rmg_reaction.products]):
                raise InputError(f'All species in a reaction must be labeled (and the labels must correspond '
                                 f'to respective Species in ARC). If an RMG Reaction object was passes, make '
                                 f'sure that all species in the reactants and products are correctly labeled. '
                                 f'Problematic reaction: {self.label}')
            self.reactants = [spc.label for spc in self.rmg_reaction.reactants]
            self.products = [spc.label for spc in self.rmg_reaction.products]
        self.set_label_reactants_products()
        if self.ts_label is None:
            self.ts_label = reaction_dict['ts_label'] if 'ts_label' in reaction_dict else None
        self.r_species = [r.from_dict() for r in reaction_dict['r_species']] if 'r_species' in reaction_dict else list()
        self.p_species = [p.from_dict() for p in reaction_dict['p_species']] if 'p_species' in reaction_dict else list()
        self.ts_species = reaction_dict['ts_species'].from_dict() if 'ts_species' in reaction_dict else None

        self.long_kinetic_description = reaction_dict['long_kinetic_description'] \
            if 'long_kinetic_description' in reaction_dict else ''
        self.ts_methods = reaction_dict['ts_methods'] if 'ts_methods' in reaction_dict else default_ts_methods
        self.ts_methods = [tsm.lower() for tsm in self.ts_methods]
        self.ts_xyz_guess = reaction_dict['ts_xyz_guess'] if 'ts_xyz_guess' in reaction_dict else list()
        self.preserve_param_in_scan = reaction_dict['preserve_param_in_scan'] \
            if 'preserve_param_in_scan' in reaction_dict else None
        self._atom_map = reaction_dict['atom_map'] if 'atom_map' in reaction_dict else None

    def set_label_reactants_products(self):
        """A helper function for settings the label, reactants, and products attributes for a Reaction"""
        # first make sure that reactants and products labels are defines (most often used)
        if self.reactants is None or self.products is None:
            if self.label:
                if self.arrow not in self.label:
                    raise ReactionError(f'A reaction label must contain an arrow ("{self.arrow}")')
                reactants, products = self.label.split(self.arrow)
                if self.plus in reactants:
                    self.reactants = reactants.split(self.plus)
                else:
                    self.reactants = [reactants]
                if self.plus in products:
                    self.products = products.split(self.plus)
                else:
                    self.products = [products]
            elif self.rmg_reaction is not None:
                self.reactants = [r.label for r in self.rmg_reaction.reactants]
                self.products = [p.label for p in self.rmg_reaction.products]
        if not self.label:
            if self.reactants is not None and self.products is not None:
                self.label = self.arrow.join([self.plus.join(r for r in self.reactants),
                                              self.plus.join(p for p in self.products)])
            elif self.r_species is not None and self.p_species is not None:
                self.label = self.arrow.join([self.plus.join(r.label for r in self.r_species),
                                              self.plus.join(p.label for p in self.p_species)])
            elif self.rmg_reaction is not None:
                # this will probably never be executed, but OK to keep
                self.label = self.arrow.join([self.plus.join(r.label for r in self.rmg_reaction.reactants),
                                              self.plus.join(p.label for p in self.rmg_reaction.products)])
        if self.rmg_reaction is None:
            self.rmg_reaction_from_arc_species()
        elif not self.label and (self.reactants is None or self.products is None):
            raise ReactionError('Either a label or reactants and products lists must be specified')

    def rmg_reaction_to_str(self) -> str:
        """A helper function for dumping the RMG Reaction object as a string for the YAML restart dictionary"""
        return self.arrow.join([self.plus.join(r.molecule[0].copy(deep=True).to_smiles()
                                               for r in self.rmg_reaction.reactants),
                                self.plus.join(p.molecule[0].copy(deep=True).to_smiles()
                                               for p in self.rmg_reaction.products)])

    def rmg_reaction_from_str(self, reaction_string: str):
        """A helper function for regenerating the RMG Reaction object from a string representation"""
        reactants, products = reaction_string.split(self.arrow)
        reactants = [Species(smiles=smiles) for smiles in reactants.split(self.plus)]
        products = [Species(smiles=smiles) for smiles in products.split(self.plus)]
        self.rmg_reaction = Reaction(reactants=reactants, products=products)

    def rmg_reaction_from_arc_species(self):
        """
        A helper function for generating the RMG Reaction object from ARCSpecies
        Used for determining the family
        """
        if self.rmg_reaction is None and len(self.r_species) and len(self.p_species) and \
                all([arc_spc.mol is not None for arc_spc in self.r_species + self.p_species]):
            reactants = [Species(molecule=[r.mol]) for r in self.r_species]
            for i, reac in enumerate(self.r_species):
                reactants[i].label = reac.label
            products = [Species(molecule=[p.mol]) for p in self.p_species]
            for i, prod in enumerate(self.p_species):
                products[i].label = prod.label
            self.rmg_reaction = Reaction(reactants=reactants, products=products)

    def arc_species_from_rmg_reaction(self):
        """
        A helper function for generating the ARC Species (.r_species and .p_species) from the RMG Reaction object
        """
        if self.rmg_reaction is not None and not len(self.r_species) and not len(self.p_species):
            self.r_species = [ARCSpecies(label=spc.label, mol=spc.molecule[0]) for spc in self.rmg_reaction.reactants]
            self.p_species = [ARCSpecies(label=spc.label, mol=spc.molecule[0]) for spc in self.rmg_reaction.products]

    def determine_rxn_multiplicity(self):
        """A helper function for determining the surface multiplicity"""
        if self.multiplicity is None:
            ordered_r_mult_list, ordered_p_mult_list = list(), list()
            if len(self.r_species):
                if len(self.r_species) == 1:
                    self.multiplicity = self.r_species[0].multiplicity
                elif len(self.r_species) == 2:
                    ordered_r_mult_list = sorted([self.r_species[0].multiplicity,
                                                  self.r_species[1].multiplicity])
                elif len(self.r_species) == 3:
                    ordered_r_mult_list = sorted([self.r_species[0].multiplicity,
                                                  self.r_species[1].multiplicity,
                                                  self.r_species[2].multiplicity])
                if len(self.p_species) == 1:
                    self.multiplicity = self.p_species[0].multiplicity
                elif len(self.p_species) == 2:
                    ordered_p_mult_list = sorted([self.p_species[0].multiplicity,
                                                  self.p_species[1].multiplicity])
                elif len(self.p_species) == 3:
                    ordered_p_mult_list = sorted([self.p_species[0].multiplicity,
                                                  self.p_species[1].multiplicity,
                                                  self.p_species[2].multiplicity])
            elif self.rmg_reaction is not None:
                if len(self.rmg_reaction.reactants) == 1:
                    self.multiplicity = self.rmg_reaction.reactants[0].molecule[0].multiplicity
                elif len(self.rmg_reaction.reactants) == 2:
                    ordered_r_mult_list = sorted([self.rmg_reaction.reactants[0].molecule[0].multiplicity,
                                                  self.rmg_reaction.reactants[1].molecule[0].multiplicity])
                elif len(self.rmg_reaction.reactants) == 3:
                    ordered_r_mult_list = sorted([self.rmg_reaction.reactants[0].molecule[0].multiplicity,
                                                  self.rmg_reaction.reactants[1].molecule[0].multiplicity,
                                                  self.rmg_reaction.reactants[2].molecule[0].multiplicity])
                if len(self.rmg_reaction.products) == 1:
                    self.multiplicity = self.rmg_reaction.products[0].molecule[0].multiplicity
                elif len(self.rmg_reaction.products) == 2:
                    ordered_p_mult_list = sorted([self.rmg_reaction.products[0].molecule[0].multiplicity,
                                                  self.rmg_reaction.products[1].molecule[0].multiplicity])
                elif len(self.rmg_reaction.products) == 3:
                    ordered_p_mult_list = sorted([self.rmg_reaction.products[0].molecule[0].multiplicity,
                                                  self.rmg_reaction.products[1].molecule[0].multiplicity,
                                                  self.rmg_reaction.products[2].molecule[0].multiplicity])
            if self.multiplicity is None:
                if ordered_r_mult_list == [1, 1]:
                    self.multiplicity = 1  # S + S = D
                elif ordered_r_mult_list == [1, 2]:
                    self.multiplicity = 2  # S + D = D
                elif ordered_r_mult_list == [2, 2]:
                    # D + D = S or T
                    if ordered_p_mult_list in [[1, 1], [1, 1, 1]]:
                        self.multiplicity = 1
                    elif ordered_p_mult_list in [[1, 3], [1, 1, 3]]:
                        self.multiplicity = 3
                    else:
                        self.multiplicity = 1
                        logger.warning(f'ASSUMING a multiplicity of 1 (singlet) for reaction {self.label}')
                elif ordered_r_mult_list == [1, 3]:
                    self.multiplicity = 3  # S + T = T
                elif ordered_r_mult_list == [2, 3]:
                    # D + T = D or Q
                    if ordered_p_mult_list in [[1, 2], [1, 1, 2]]:
                        self.multiplicity = 2
                    elif ordered_p_mult_list in [[1, 4], [1, 1, 4]]:
                        self.multiplicity = 4
                    else:
                        self.multiplicity = 2
                        logger.warning(f'ASSUMING a multiplicity of 2 (doublet) for reaction {self.label}')
                elif ordered_r_mult_list == [3, 3]:
                    # T + T = S or T or quintet
                    if ordered_p_mult_list in [[1, 1], [1, 1, 1]]:
                        self.multiplicity = 1
                    elif ordered_p_mult_list in [[1, 3], [1, 1, 3]]:
                        self.multiplicity = 3
                    elif ordered_p_mult_list in [[1, 5], [1, 1, 5]]:
                        self.multiplicity = 5
                    else:
                        self.multiplicity = 3
                        logger.warning(f'ASSUMING a multiplicity of 3 (triplet) for reaction {self.label}')
                elif ordered_r_mult_list == [1, 1, 1]:
                    self.multiplicity = 1  # S + S + S = S
                elif ordered_r_mult_list == [1, 1, 2]:
                    self.multiplicity = 2  # S + S + D = D
                elif ordered_r_mult_list == [1, 1, 3]:
                    self.multiplicity = 3  # S + S + T = T
                elif ordered_r_mult_list == [1, 2, 2]:
                    # S + D + D = S or T
                    if ordered_p_mult_list in [[1, 1], [1, 1, 1]]:
                        self.multiplicity = 1
                    elif ordered_p_mult_list in [[1, 3], [1, 1, 3]]:
                        self.multiplicity = 3
                    else:
                        self.multiplicity = 1
                        logger.warning(f'ASSUMING a multiplicity of 1 (singlet) for reaction {self.label}')
                elif ordered_r_mult_list == [2, 2, 2]:
                    # D + D + D = D or Q
                    if ordered_p_mult_list in [[1, 2], [1, 1, 2]]:
                        self.multiplicity = 2
                    elif ordered_p_mult_list in [[1, 4], [1, 1, 4]]:
                        self.multiplicity = 4
                    else:
                        self.multiplicity = 2
                        logger.warning(f'ASSUMING a multiplicity of 2 (doublet) for reaction {self.label}')
                elif ordered_r_mult_list == [1, 2, 3]:
                    # S + D + T = D or Q
                    if ordered_p_mult_list in [[1, 2], [1, 1, 2]]:
                        self.multiplicity = 2
                    elif ordered_p_mult_list in [[1, 4], [1, 1, 4]]:
                        self.multiplicity = 4
                    self.multiplicity = 2
                    logger.warning(f'ASSUMING a multiplicity of 2 (doublet) for reaction {self.label}')
                else:
                    raise ReactionError(f'Could not determine multiplicity for reaction {self.label}')
            logger.info(f'Setting multiplicity of reaction {self.label} to {self.multiplicity}')

    def determine_rxn_charge(self):
        """A helper function for determining the surface charge"""
        if len(self.r_species):
            self.charge = sum([r.charge for r in self.r_species])

    def determine_family(self, rmg_database):
        """Determine the RMG family and saves the (family, own reverse) tuple in the ``family`` attribute"""
        if self.rmg_reaction is not None:
            self.family, self.family_own_reverse = rmgdb.determine_reaction_family(rmgdb=rmg_database,
                                                                                   reaction=self.rmg_reaction)

    def check_ts(self, verbose: bool = True) -> bool:
        """
        Check that the TS E0 is above both reactants and products wells.

        Args:
            verbose (bool, optional): Whether to print logging messages.

        Returns:
            bool: Whether the TS energy is above both reactants and products wells, ``True`` if it is.
        """
        r_e0 = None if any([spc.e0 is None for spc in self.r_species]) \
            else sum(spc.e0 for spc in self.r_species)
        p_e0 = None if any([spc.e0 is None for spc in self.p_species]) \
            else sum(spc.e0 for spc in self.p_species)
        ts_e0 = self.ts_species.e0
        min_e = extermum_list([r_e0, p_e0, ts_e0], return_min=True)
        if any([val is None for val in [r_e0, p_e0, ts_e0]]):
            if verbose:
                logger.error(f"Could not get E0's of all species in reaction {self.label}. Cannot check TS E0.\n")
                r_text = f'{r_e0:.2f} kJ/mol' if r_e0 is not None else 'None'
                ts_text = f'{ts_e0:.2f} kJ/mol' if ts_e0 is not None else 'None'
                p_text = f'{p_e0:.2f} kJ/mol' if p_e0 is not None else 'None'
                logger.info(f"Reactants E0: {r_text}\n"
                            f"TS E0: {ts_text}\n"
                            f"Products E0: {p_text}")
            return True
        if ts_e0 < r_e0 or ts_e0 < p_e0:
            if verbose:
                logger.error(f'TS of reaction {self.label} has a lower E0 value than expected:\n')
                logger.info(f'Reactants: {r_e0 - min_e:.2f} kJ/mol\n'
                            f'TS: {ts_e0 - min_e:.2f} kJ/mol'
                            f'\nProducts: {p_e0 - min_e:.2f} kJ/mol')
            return False
        if verbose:
            logger.info(f'Reaction {self.label} has the following path energies:\n'
                        f'Reactants: {r_e0 - min_e:.2f} kJ/mol\n'
                        f'TS: {ts_e0 - min_e:.2f} kJ/mol\n'
                        f'Products: {p_e0 - min_e:.2f} kJ/mol')
        return True

    def check_attributes(self):
        """Check that the Reaction object is defined correctly"""
        self.set_label_reactants_products()
        if not self.label:
            raise ReactionError('A reaction seems to not be defined correctly')
        if self.arrow not in self.label:
            raise ReactionError(f'A reaction label must include a double ended arrow with spaces on both '
                                f'sides: "{self.arrow}". Got:{self.label}')
        if '+' in self.label and self.plus not in self.label:
            raise ReactionError(f'Reactants or products in a reaction label must separated with {self.plus} '
                                f'(has spaces on both sides). Got:{self.label}')
        species_labels = self.label.split(self.arrow)
        reactants = species_labels[0].split(self.plus)
        products = species_labels[1].split(self.plus)
        if self.reactants is not None:
            for reactant in reactants:
                if reactant not in self.reactants:
                    raise ReactionError(f'Reactant {reactant} from the reaction label {self.label} '
                                        f'not in self.reactants ({self.reactants})')
            for reactant in self.reactants:
                if reactant not in reactants:
                    raise ReactionError(f'Reactant {reactant} not in the reaction label ({self.label})')
        if self.products is not None:
            for product in products:
                if product not in self.products:
                    raise ReactionError(f'Product {product} from the reaction label {self.label} '
                                        f'not in self.products ({self.products})')
            for product in self.products:
                if product not in products:
                    raise ReactionError(f'Product {product} not in the reaction label ({self.label})')
        if self.r_species is not None:
            for reactant in self.r_species:
                if reactant.label not in self.reactants:
                    raise ReactionError(f'Reactant {reactant.label} from {self.label} '
                                        f'not in self.reactants ({self.reactants})')
            for reactant in reactants:
                if reactant not in [r.label for r in self.r_species]:
                    raise ReactionError(f'Reactant {reactant} from the reaction label {self.label} '
                                        f'not in self.r_species ({[r.label for r in self.r_species]})')
            for reactant in self.reactants:
                if reactant not in [r.label for r in self.r_species]:
                    raise ReactionError(f'Reactant {reactant} not in '
                                        f'self.r_species ({[r.label for r in self.r_species]})')
        if self.p_species is not None:
            for product in self.p_species:
                if product.label not in self.products:
                    raise ReactionError(f'Product {product.label} from {self.label} '
                                        f'not in self.products ({self.reactants})')
            for product in products:
                if product not in [p.label for p in self.p_species]:
                    raise ReactionError(f'Product {product} from the reaction label {self.label} '
                                        f'not in self.p_species ({[p.label for p in self.p_species]})')
            for product in self.products:
                if product not in [p.label for p in self.p_species]:
                    raise ReactionError(f'Product {product} not in '
                                        f'self.p_species ({[p.label for p in self.p_species]})')

    def check_atom_balance(self,
                           ts_xyz: Optional[dict] = None,
                           raise_error: bool = True,
                           ) -> bool:
        """
        Check atom balance between reactants, TSs, and product wells.

        Args:
            ts_xyz (Optional[dict]): An alternative TS xyz to check.
                                     If unspecified, user guesses and the ts_species will be checked.
            raise_error (bool, optional): Whether to raise an error if an imbalance is found.

        Raises:
            ReactionError: If not all wells and TSs are atom balanced.
                           The exception is not raised if ``raise_error`` is ``False``.

        Returns:
            bool: Whether all wells and TSs are atom balanced.
        """
        self.arc_species_from_rmg_reaction()

        balanced_wells, balanced_ts_xyz, balanced_xyz_guess, balanced_ts_species_mol, balanced_ts_species_xyz = \
            True, True, True, True, True
        r_well, p_well = '', ''

        for reactant in self.r_species:
            count = self.get_species_count(species=reactant, well=0)
            xyz = reactant.get_xyz(generate=True)
            if xyz is not None and xyz:
                r_well += (xyz_to_str(xyz) + '\n') * count
            else:
                r_well = ''
                break

        for product in self.p_species:
            count = self.get_species_count(species=product, well=1)
            xyz = product.get_xyz(generate=True)
            if xyz is not None and xyz:
                p_well += (xyz_to_str(xyz) + '\n') * count
            else:
                p_well = ''
                break

        if r_well:
            for xyz_guess in self.ts_xyz_guess:
                balanced_xyz_guess *= check_atom_balance(entry_1=xyz_guess, entry_2=r_well)

            if p_well:
                balanced_wells = check_atom_balance(entry_1=r_well, entry_2=p_well)

            if ts_xyz:
                balanced_ts_xyz = check_atom_balance(entry_1=ts_xyz, entry_2=r_well)

            if self.ts_species is not None:
                if self.ts_species.mol is not None:
                    balanced_ts_species_mol = check_atom_balance(entry_1=self.ts_species.mol, entry_2=r_well)

                ts_xyz = self.ts_species.get_xyz()
                if ts_xyz is not None:
                    balanced_ts_species_xyz = check_atom_balance(entry_1=self.ts_species.get_xyz(), entry_2=r_well)

        if not balanced_wells:
            logger.error(f'The reactant(s) and product(s) wells of reaction {self.label}, are not atom balanced.')
        if not balanced_ts_xyz:
            logger.error(f'The generated TS xyz for reaction {self.label} '
                         f'is not atom balances with the reactant(s) well.')
        if not balanced_ts_species_mol:
            logger.error(f'The TS mol for reaction {self.label} is not atom balances with the reactant(s) well.')
        if not balanced_ts_species_xyz:
            logger.error(f'The TS coordinates for reaction {self.label} '
                         f'are not atom balances with the reactant(s) well.')
        if not balanced_xyz_guess:
            logger.error(f'Check TS xyz user guesses of reaction {self.label}, '
                         f'some are not atom balances with the reactant(s) well.')
        if not all([balanced_wells, balanced_ts_xyz, balanced_ts_species_mol,
                    balanced_ts_species_xyz, balanced_xyz_guess]):
            if raise_error:
                raise ReactionError(f'Reaction {self.label} is not atom balanced.')
            return False

        return True

    def get_species_count(self,
                          species: ARCSpecies,
                          well: int = 0,
                          ) -> int:
        """
        Get the number of times a species participates in the reactants or products well.

        Args:
            species (ARCSpecies): The species to check.
            well (int, optional): Either ``0`` or ``1`` for the reactants or products well, respectively.

        Returns:
            Union[int, None]: The number of times this species appears in the respective well.
        """
        well_str = self.label.split('<=>')[well]
        count = well_str.startswith(f'{species.label} ') + \
                well_str.count(f' {species.label} ') + \
                well_str.endswith(f' {species.label}')
        return count

    def get_atom_map(self, verbose: int = 0) -> Optional[List[int]]:
        """
        Get the atom mapping of the reactant atoms to the product atoms.
        I.e., an atom map of [0, 2, 1] means that reactant atom 0 matches product atom 0,
        reactant atom 1 matches product atom 2, and reactant atom 2 matches product atom 1.

        Employs the Kabsch, Hungarian, and Uno algorithms to exhaustively locate
        the best alignment for non-oriented, non-ordered 3D structures.

        Args:
            verbose (int): The verbosity level (0-4).

        Returns: Optional[List[int]]
            The atom map.
        """
        atom_map = None
        try:
            reactants = QCMolecule.from_data(
                data='\n--\n'.join(xyz_to_str(reactant.get_xyz()) for reactant in self.r_species),
                molecular_charge=self.charge,
                molecular_multiplicity=self.multiplicity,
                fragment_charges=[reactant.charge for reactant in self.r_species],
                fragment_multiplicities=[reactant.multiplicity for reactant in self.r_species],
                orient=False,
            )
            products = QCMolecule.from_data(
                data='\n--\n'.join(xyz_to_str(product.get_xyz()) for product in self.p_species),
                molecular_charge=self.charge,
                molecular_multiplicity=self.multiplicity,
                fragment_charges=[product.charge for product in self.p_species],
                fragment_multiplicities=[product.multiplicity for product in self.p_species],
                orient=False,
            )
        except ValidationError as e:
            logger.warning(f'Could not get atom map for {self}, got:\n{e}')
        else:
            data = products.align(ref_mol=reactants, verbose=verbose)[1]
            atom_map = data['mill'].atommap.tolist()
        return atom_map
