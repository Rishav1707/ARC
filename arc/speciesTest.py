#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
This module contains unit tests of the arc.species module
"""

from __future__ import (absolute_import, division, print_function, unicode_literals)
import unittest

from rmgpy.molecule.molecule import Molecule
from rmgpy.species import Species
from rmgpy.reaction import Reaction

from arc.species import ARCSpecies, TSGuess, get_xyz_string, get_xyz_matrix, mol_from_xyz, check_xyz

################################################################################


class TestARCSpecies(unittest.TestCase):
    """
    Contains unit tests for the ARCSpecies class
    """
    @classmethod
    def setUpClass(cls):
        """
        A method that is run before all unit tests in this class.
        """
        cls.maxDiff = None
        # Method 1: RMG Species object (here by SMILES)
        cls.spc1_rmg = Species(molecule=[Molecule().fromSMILES(str('C=C[O]'))])  # delocalized radical + amine
        cls.spc1_rmg.label = str('vinoxy')
        cls.spc1 = ARCSpecies(rmg_species=cls.spc1_rmg)

        # Method 2: ARCSpecies object by XYZ (also give SMILES for thermo BAC)
        oh_xyz = str("""O       0.00000000    0.00000000   -0.12002167
        H       0.00000000    0.00000000    0.85098324""")
        cls.spc2 = ARCSpecies(label=str('OH'), xyz=oh_xyz, smiles=str('[OH]'), multiplicity=2, charge=0)

        # Method 3: ARCSpecies object by SMILES
        cls.spc3 = ARCSpecies(label=str('methylamine'), smiles=str('CN'), multiplicity=1, charge=0)

        # Method 4: ARCSpecies object by RMG Molecule object
        mol4 = Molecule().fromSMILES(str('C=CC'))
        cls.spc4 = ARCSpecies(label=str('propene'), mol=mol4, multiplicity=1, charge=0)

        # Method 5: ARCSpecies by AdjacencyList (to generate AdjLists, see https://rmg.mit.edu/molecule_search)
        n2h4_adj = str("""1 N u0 p1 c0 {2,S} {3,S} {4,S}
        2 N u0 p1 c0 {1,S} {5,S} {6,S}
        3 H u0 p0 c0 {1,S}
        4 H u0 p0 c0 {1,S}
        5 H u0 p0 c0 {2,S}
        6 H u0 p0 c0 {2,S}""")
        cls.spc5 = ARCSpecies(label=str('N2H4'), adjlist=n2h4_adj, multiplicity=1, charge=0)

        n3_xyz = str("""N      -1.1997440839    -0.1610052059     0.0274738287
        H      -1.4016624407    -0.6229695533    -0.8487034080
        H      -0.0000018759     1.2861082773     0.5926077870
        N       0.0000008520     0.5651072858    -0.1124621525
        H      -1.1294692206    -0.8709078271     0.7537518889
        N       1.1997613019    -0.1609980472     0.0274604887
        H       1.1294795781    -0.8708998550     0.7537444446
        H       1.4015274689    -0.6230592706    -0.8487058662""")
        cls.spc6 = ARCSpecies(label=str('N3'), xyz=n3_xyz, multiplicity=1, charge=0, smiles=str('NNN'))

    def test_conformers(self):
        """Test conformer generation"""
        self.spc1.generate_conformers()  # vinoxy has two res. structures, each is assgined two conformers (rdkit/ob)
        self.assertEqual(len(self.spc1.conformers), 4)
        self.assertEqual(len(self.spc1.conformers), len(self.spc1.conformer_energies))

    def test_rmg_species_conversion_into_arc_species(self):
        """Test the conversion of an RMG species into an ARCSpecies"""
        self.spc1_rmg.label = None
        self.spc = ARCSpecies(rmg_species=self.spc1_rmg, label=str('vinoxy'))
        self.assertEqual(self.spc.label, str('vinoxy'))
        self.assertEqual(self.spc.multiplicity, 2)
        self.assertEqual(self.spc.charge, 0)

    def test_determine_rotors(self):
        """Test determination of rotors in ARCSpecies"""
        self.spc1.determine_rotors()
        self.spc2.determine_rotors()
        self.spc3.determine_rotors()
        self.spc4.determine_rotors()
        self.spc5.determine_rotors()
        self.spc6.determine_rotors()

        self.assertEqual(len(self.spc1.rotors_dict), 1)
        self.assertEqual(len(self.spc2.rotors_dict), 0)
        self.assertEqual(len(self.spc3.rotors_dict), 1)
        self.assertEqual(len(self.spc4.rotors_dict), 1)
        self.assertEqual(len(self.spc5.rotors_dict), 1)
        self.assertEqual(len(self.spc6.rotors_dict), 2)

        self.assertEqual(self.spc1.rotors_dict[0][str('pivots')], [2, 3])
        self.assertEqual(self.spc1.rotors_dict[0][str('scan')], [4, 2, 3, 1])
        self.assertTrue(all([t in [2, 4, 5] for t in self.spc1.rotors_dict[0][str('top')]]))
        self.assertEqual(self.spc1.rotors_dict[0][str('times_dihedral_set')], 0)
        self.assertEqual(self.spc3.rotors_dict[0][str('pivots')], [1, 2])
        self.assertEqual(self.spc4.rotors_dict[0][str('pivots')], [1, 2])
        self.assertEqual(self.spc5.rotors_dict[0][str('pivots')], [1, 2])
        self.assertEqual(self.spc6.rotors_dict[0][str('pivots')], [1, 4])
        self.assertEqual(self.spc6.rotors_dict[0][str('scan')], [2, 1, 4, 6])
        self.assertEqual(len(self.spc6.rotors_dict[0][str('top')]), 3)
        self.assertTrue(all([t in [1, 5, 2] for t in self.spc6.rotors_dict[0][str('top')]]))
        self.assertEqual(self.spc6.rotors_dict[1][str('pivots')], [4, 6])
        self.assertEqual(self.spc6.rotors_dict[1][str('scan')], [1, 4, 6, 7])
        self.assertEqual(len(self.spc6.rotors_dict[1][str('top')]), 3)
        self.assertTrue(all([t in [6, 7, 8] for t in self.spc6.rotors_dict[1][str('top')]]))

    def test_symmetry(self):
        """Test external symmetry and chirality determination"""
        allene = ARCSpecies(label=str('allene'), smiles=str('C=C=C'), multiplicity=1, charge=0)
        allene.final_xyz = """C  -1.01646   0.10640  -0.91445
                              H  -1.39000   1.03728  -1.16672
                              C   0.00000   0.00000   0.00000
                              C   1.01653  -0.10640   0.91438
                              H  -1.40975  -0.74420  -1.35206
                              H   0.79874  -0.20864   1.92036
                              H   2.00101  -0.08444   0.59842"""
        allene.determine_symmetry()
        self.assertEqual(allene.optical_isomers, 1)
        self.assertEqual(allene.external_symmetry, 4)

        ammonia = ARCSpecies(label=str('ammonia'), smiles=str('N'), multiplicity=1, charge=0)
        ammonia.final_xyz = """N  0.06617   0.20024   0.13886
                               H  -0.62578  -0.34119   0.63709
                               H  -0.32018   0.51306  -0.74036
                               H   0.87976  -0.37219  -0.03564"""
        ammonia.determine_symmetry()
        self.assertEqual(ammonia.optical_isomers, 1)
        self.assertEqual(ammonia.external_symmetry, 3)

        methane = ARCSpecies(label=str('methane'), smiles=str('C'), multiplicity=1, charge=0)
        methane.final_xyz = """C   0.00000   0.00000   0.00000
                               H  -0.29717   0.97009  -0.39841
                               H   1.08773  -0.06879   0.01517
                               H  -0.38523  -0.10991   1.01373
                               H -0.40533  -0.79140  -0.63049"""
        methane.determine_symmetry()
        self.assertEqual(methane.optical_isomers, 1)
        self.assertEqual(methane.external_symmetry, 12)

        chiral = ARCSpecies(label=str('chiral'), smiles=str('C(C)(O)(N)'), multiplicity=1, charge=0)
        chiral.final_xyz = """C                 -0.49341625    0.37828349    0.00442108
                              H                 -1.56331545    0.39193350    0.01003359
                              N                  0.01167132    1.06479568    1.20212111
                              H                  1.01157784    1.05203730    1.19687531
                              H                 -0.30960193    2.01178202    1.20391932
                              O                 -0.03399634   -0.97590449    0.00184366
                              H                 -0.36384913   -1.42423238   -0.78033350
                              C                  0.02253835    1.09779040   -1.25561654
                              H                 -0.34510997    0.59808430   -2.12741255
                              H                 -0.32122209    2.11106387   -1.25369100
                              H                  1.09243518    1.08414066   -1.26122530"""
        chiral.determine_symmetry()
        self.assertEqual(chiral.optical_isomers, 2)
        self.assertEqual(chiral.external_symmetry, 1)

        s8 = ARCSpecies(label=str('s8'), smiles=str('S1SSSSSSS1'), multiplicity=1, charge=0)
        s8.final_xyz = """S   2.38341   0.12608   0.09413
                          S   1.45489   1.88955  -0.13515
                          S  -0.07226   2.09247   1.14966
                          S  -1.81072   1.52327   0.32608
                          S  -2.23488  -0.39181   0.74645
                          S  -1.60342  -1.62383  -0.70542
                          S   0.22079  -2.35820  -0.30909
                          S   1.66220  -1.25754  -1.16665"""
        s8.determine_symmetry()
        self.assertEqual(s8.optical_isomers, 1)
        self.assertEqual(s8.external_symmetry, 8)

        water = ARCSpecies(label=str('H2O'), smiles=str('O'), multiplicity=1, charge=0)
        water.final_xyz = """O   0.19927   0.29049  -0.11186
                             H   0.50770  -0.61852  -0.09124
                             H  -0.70697   0.32803   0.20310"""
        water.determine_symmetry()
        self.assertEqual(water.optical_isomers, 1)
        self.assertEqual(water.external_symmetry, 2)

    def test_xyz_format_conversion(self):
        """Test conversions from string to list xyz formats"""
        xyz_str0 = """C       0.66165148    0.40274815   -0.48473823
N      -0.60397931    0.66372701    0.06716371
H      -1.42268656   -0.49732107   -0.22387123
H      -0.49930106    0.65310204    1.08530923
H      -2.21157969   -0.45292568    0.41445163
H      -1.81136714   -0.32689007   -1.14689570
"""

        xyz_list, atoms, x, y, z = get_xyz_matrix(xyz_str0)

        # test all forms of input into get_xyz_string():
        xyz_str1 = get_xyz_string(xyz_list, symbol=atoms)
        xyz_str2 = get_xyz_string(xyz_list, number=[6, 7, 1, 1, 1, 1])
        mol, _ = mol_from_xyz(xyz_str0)
        xyz_str3 = get_xyz_string(xyz_list, mol=mol)

        self.assertEqual(xyz_str0, xyz_str1)
        self.assertEqual(xyz_str1, xyz_str2)
        self.assertEqual(xyz_str2, xyz_str3)
        self.assertEqual(atoms, ['C', 'N', 'H', 'H', 'H', 'H'])
        self.assertEqual(x, [0.66165148, -0.60397931, -1.42268656, -0.49930106, -2.21157969, -1.81136714])
        self.assertEqual(y, [0.40274815, 0.66372701, -0.49732107, 0.65310204, -0.45292568, -0.32689007])
        self.assertEqual(z, [-0.48473823, 0.06716371, -0.22387123, 1.08530923, 0.41445163, -1.1468957])

    def test_is_linear(self):
        """Test determination of molecule linearity by xyz"""
        xyz1 = """C  0.000000    0.000000    0.000000
                  O  0.000000    0.000000    1.159076
                  O  0.000000    0.000000   -1.159076"""  # a trivial case
        xyz2 = """C  0.6616514836    0.4027481525   -0.4847382281
                  N -0.6039793084    0.6637270105    0.0671637135
                  H -1.4226865648   -0.4973210697   -0.2238712255
                  H -0.4993010635    0.6531020442    1.0853092315
                  H -2.2115796924   -0.4529256762    0.4144516252
                  H -1.8113671395   -0.3268900681   -1.1468957003"""  # a non linear molecule
        xyz3 = """N  0.0000000000     0.0000000000     0.3146069129
                  O -1.0906813653     0.0000000000    -0.1376405244
                  O  1.0906813653     0.0000000000    -0.1376405244"""  # a non linear 3-atom molecule
        xyz4 = """N  0.0000000000     0.0000000000     0.1413439534
                  H -0.8031792912     0.0000000000    -0.4947038368
                  H  0.8031792912     0.0000000000    -0.4947038368"""  # a non linear 3-atom molecule
        xyz5 = """S -0.5417345330        0.8208150346        0.0000000000
                  O  0.9206183692        1.6432038228        0.0000000000
                  H -1.2739176462        1.9692549926        0.0000000000"""  # a non linear 3-atom molecule
        xyz6 = """N  1.18784533    0.98526702    0.00000000
                  C  0.04124533    0.98526702    0.00000000
                  H -1.02875467    0.98526702    0.00000000""" # linear
        xyz7 = """C -4.02394116    0.56169428    0.00000000
                  H -5.09394116    0.56169428    0.00000000
                  C -2.82274116    0.56169428    0.00000000
                  H -1.75274116    0.56169428    0.00000000""" # linear
        xyz8 = """C -1.02600933    2.12845307    0.00000000
                  C -0.77966935    0.95278385    0.00000000
                  H -1.23666197    3.17751246    0.00000000
                  H -0.56023545   -0.09447399    0.00000000""" # just 0.5 degree off from linearity, so NOT linear...
        xyz9 = """C -1.1998 0.1610 0.0275
                  C -1.4021 0.6223 -0.8489
                  C -1.48302 0.80682 -1.19946"""  # just 3 points in space on a straight line (not a physical molecule)
        spc1 = ARCSpecies(label=str('test_spc'), xyz=xyz1, multiplicity=1, charge=0, smiles=str('C'))
        spc2 = ARCSpecies(label=str('test_spc'), xyz=xyz2, multiplicity=1, charge=0, smiles=str('C'))
        spc3 = ARCSpecies(label=str('test_spc'), xyz=xyz3, multiplicity=1, charge=0, smiles=str('C'))
        spc4 = ARCSpecies(label=str('test_spc'), xyz=xyz4, multiplicity=1, charge=0, smiles=str('C'))
        spc5 = ARCSpecies(label=str('test_spc'), xyz=xyz5, multiplicity=1, charge=0, smiles=str('C'))
        spc6 = ARCSpecies(label=str('test_spc'), xyz=xyz6, multiplicity=1, charge=0, smiles=str('C'))
        spc7 = ARCSpecies(label=str('test_spc'), xyz=xyz7, multiplicity=1, charge=0, smiles=str('C'))
        spc8 = ARCSpecies(label=str('test_spc'), xyz=xyz8, multiplicity=1, charge=0, smiles=str('C'))
        spc9 = ARCSpecies(label=str('test_spc'), xyz=xyz9, multiplicity=1, charge=0, smiles=str('C'))

        self.assertTrue(spc1.is_linear())
        self.assertTrue(spc6.is_linear())
        self.assertTrue(spc7.is_linear())
        self.assertTrue(spc9.is_linear())
        self.assertFalse(spc2.is_linear())
        self.assertFalse(spc3.is_linear())
        self.assertFalse(spc4.is_linear())
        self.assertFalse(spc5.is_linear())
        self.assertFalse(spc8.is_linear())

    def test_charge_and_multiplicity(self):
        """Test determination of molecule charge and multiplicity"""
        spc1 = ARCSpecies(label='spc1', mol=Molecule(SMILES=str('C[CH]C')), generate_thermo=False)  # 2
        spc2 = ARCSpecies(label='spc2', mol=Molecule(SMILES=str('CCC')), generate_thermo=False)  # 1
        spc3 = ARCSpecies(label='spc3', smiles=str('N[NH]'), generate_thermo=False)  # 2
        spc4 = ARCSpecies(label='spc4', smiles=str('NNN'), generate_thermo=False)  # 1
        adj1 = """multiplicity 2
                  1 O u1 p2 c0 {2,S}
                  2 H u0 p0 c0 {1,S}
               """
        adj2 = """1 C u0 p0 c0 {2,S} {4,S} {5,S} {6,S}
                  2 N u0 p1 c0 {1,S} {3,S} {7,S}
                  3 O u0 p2 c0 {2,S} {8,S}
                  4 H u0 p0 c0 {1,S}
                  5 H u0 p0 c0 {1,S}
                  6 H u0 p0 c0 {1,S}
                  7 H u0 p0 c0 {2,S}
                  8 H u0 p0 c0 {3,S}
               """
        spc5 = ARCSpecies(label='spc5', adjlist=str(adj1), generate_thermo=False)  # 2
        spc6 = ARCSpecies(label='spc6', adjlist=str(adj2), generate_thermo=False)  # 1
        xyz1 = """O       0.00000000    0.00000000   -0.10796235
                  H       0.00000000    0.00000000    0.86318839"""
        xyz2 = """N      -0.74678912   -0.11808620    0.00000000
                  C       0.70509190    0.01713703    0.00000000
                  H       1.11547042   -0.48545356    0.87928385
                  H       1.11547042   -0.48545356   -0.87928385
                  H       1.07725194    1.05216961    0.00000000
                  H      -1.15564250    0.32084669    0.81500594
                  H      -1.15564250    0.32084669   -0.81500594"""
        spc7 = ARCSpecies(label='spc7', xyz=xyz1, generate_thermo=False)  # 2
        spc8 = ARCSpecies(label='spc8', xyz=xyz2, generate_thermo=False)  # 1

        self.assertEqual(spc1.charge, 0)
        self.assertEqual(spc2.charge, 0)
        self.assertEqual(spc3.charge, 0)
        self.assertEqual(spc4.charge, 0)
        self.assertEqual(spc5.charge, 0)
        self.assertEqual(spc6.charge, 0)
        self.assertEqual(spc7.charge, 0)
        self.assertEqual(spc8.charge, 0)

        self.assertEqual(spc1.multiplicity, 2)
        self.assertEqual(spc2.multiplicity, 1)
        self.assertEqual(spc3.multiplicity, 2)
        self.assertEqual(spc4.multiplicity, 1)
        self.assertEqual(spc5.multiplicity, 2)
        self.assertEqual(spc6.multiplicity, 1)
        self.assertEqual(spc7.multiplicity, 2)
        self.assertEqual(spc8.multiplicity, 1)

    def test_as_dict(self):
        """Test Species.as_dict()"""
        spc_dict = self.spc3.as_dict()
        expected_dict = {'optical_isomers': None,
                         'number_of_rotors': 0,
                         'neg_freqs_trshed': [],
                         'external_symmetry': None,
                         'multiplicity': 1,
                         'arkane_file': None,
                         'E0': None,
                         'mol': """1 N u0 p1 c0 {2,S} {6,S} {7,S}
2 C u0 p0 c0 {1,S} {3,S} {4,S} {5,S}
3 H u0 p0 c0 {2,S}
4 H u0 p0 c0 {2,S}
5 H u0 p0 c0 {2,S}
6 H u0 p0 c0 {1,S}
7 H u0 p0 c0 {1,S}
""",
                         'generate_thermo': True,
                         't0': None,
                         'label': 'methylamine',
                         'long_thermo_description': spc_dict['long_thermo_description'],
                         'charge': 0,
                         'is_ts': False,
                         'final_xyz': '',
                         'opt_level': '',
                         't1': None,
                         'bond_corrections': {'C-H': 3, 'C-N': 1, 'H-N': 2},
                         'rotors_dict': {}}
        self.assertEqual(spc_dict, expected_dict)

    def test_from_dict(self):
        """Test Species.from_dict()"""
        species_dict = self.spc2.as_dict()
        spc = ARCSpecies(species_dict=species_dict)
        self.assertEqual(spc.multiplicity, 2)
        self.assertEqual(spc.charge, 0)
        self.assertEqual(spc.label, 'OH')
        self.assertEqual(spc.mol.toSMILES(), '[OH]')
        self.assertFalse(spc.is_ts)

    def test_check_xyz(self):
        """Test the check_xyz() function"""
        xyz = """
        
        
 C                 -0.67567701    1.18507660    0.04672449
 H                 -0.25592948    1.62415961    0.92757746
 H                 -2.26870864    1.38030564    0.05865317
 O                 -0.36671999   -0.21081064    0.01630374
 H                 -0.73553821   -0.63718986    0.79332805
 C                 -0.08400571    1.86907236   -1.19973252
 
 H                 -0.50375517    1.42998100   -2.08057962
 H                 -0.31518819    2.91354759   -1.17697025
 H                  0.97802159    1.73893214   -1.20769117
 O                 -3.69788377    1.55609096    0.07050345
 O                 -4.28667752    0.37487691    0.04916102
 H                 -4.01978712   -0.12970163    0.82103635
 
 """
        expected_xyz = """ C                 -0.67567701    1.18507660    0.04672449
 H                 -0.25592948    1.62415961    0.92757746
 H                 -2.26870864    1.38030564    0.05865317
 O                 -0.36671999   -0.21081064    0.01630374
 H                 -0.73553821   -0.63718986    0.79332805
 C                 -0.08400571    1.86907236   -1.19973252
 H                 -0.50375517    1.42998100   -2.08057962
 H                 -0.31518819    2.91354759   -1.17697025
 H                  0.97802159    1.73893214   -1.20769117
 O                 -3.69788377    1.55609096    0.07050345
 O                 -4.28667752    0.37487691    0.04916102
 H                 -4.01978712   -0.12970163    0.82103635"""
        new_xyz = check_xyz(xyz)
        self.assertEqual(new_xyz, expected_xyz)


class TestTSGuess(unittest.TestCase):
    """
    Contains unit tests for the TSGuess class
    """
    @classmethod
    def setUpClass(cls):
        """
        A method that is run before all unit tests in this class.
        """
        cls.maxDiff = None
        spc1 = Species().fromSMILES(str('CON=O'))
        spc1.label = str('CONO')
        spc2 = Species().fromSMILES(str('C[N+](=O)[O-]'))
        spc2.label = str('CNO2')
        rmg_reaction = Reaction(reactants=[spc1], products=[spc2])
        cls.tsg1 = TSGuess(rmg_reaction=rmg_reaction, method='AutoTST', family='H_Abstraction')
        xyz = """N       0.9177905887     0.5194617797     0.0000000000
                 H       1.8140204898     1.0381941417     0.0000000000
                 H      -0.4763167868     0.7509348722     0.0000000000
                 N       0.9992350860    -0.7048575683     0.0000000000
                 N      -1.4430010939     0.0274543367     0.0000000000
                 H      -0.6371484821    -0.7497769134     0.0000000000
                 H      -2.0093636431     0.0331190314    -0.8327683174
                 H      -2.0093636431     0.0331190314     0.8327683174"""
        cls.tsg2 = TSGuess(xyz=xyz)

    def test_as_dict(self):
        """Test TSGuess.as_dict()"""
        tsg_dict = self.tsg1.as_dict()
        expected_dict = {'method': u'autotst',
                         'energy': None,
                         'family': 'H_Abstraction',
                         'index': None,
                         'rmg_reaction': u'CON=O <=> [O-][N+](=O)C',
                         'success': None,
                         't0': None}
        self.assertEqual(tsg_dict, expected_dict)

    def test_from_dict(self):
        """Test TSGuess.from_dict()
        Also tests that the round trip to and from a dictionary ended in an RMG Reaction object"""
        ts_dict = self.tsg1.as_dict()
        tsg = TSGuess(ts_dict=ts_dict)
        self.assertEqual(tsg.method, 'autotst')
        self.assertTrue(isinstance(tsg.rmg_reaction, Reaction))




################################################################################

if __name__ == '__main__':
    unittest.main(testRunner=unittest.TextTestRunner(verbosity=2))
