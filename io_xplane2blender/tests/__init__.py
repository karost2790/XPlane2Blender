import os
import shutil
import sys
import unittest
import itertools

from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import bpy

import io_xplane2blender
from io_xplane2blender.xplane_config import setDebug, getDebug
from io_xplane2blender import xplane_config
from io_xplane2blender import xplane_helpers
from io_xplane2blender.xplane_helpers import logger, XPlaneLogger
from io_xplane2blender.xplane_types import xplane_bone, xplane_file, xplane_primitive
from ..xplane_types import xplane_file
from ..xplane_types.xplane_primitive import XPlanePrimitive
from .animation_file_mappings import mappings


#TODO: Make this import from XPlane2Blender/tests.py instead of just keeping it in sync manually
TEST_RESULTS_REGEX = "RESULT: After {num_tests} tests got {errors} errors, {fails} failures, and {skip} skipped"

FLOAT_TOLERANCE = 0.0001

__dirname__ = os.path.dirname(__file__)
TMP_DIR = os.path.realpath(os.path.join(__dirname__, '../../tests/tmp'))

FilterLinesCallback = Callable[[List[Union[float, str]]], bool]

class XPlaneTestCase(unittest.TestCase):
    def setUp(self, useLogger = True):
        dd_index = sys.argv.index('--')
        blender_args, xplane_args = sys.argv[:dd_index],sys.argv[dd_index+1:]
        setDebug('--force-xplane-debug' in xplane_args)

        if useLogger:
            self.useLogger()

        #logger.warn("---------------")

    def useLogger(self):
        debug = getDebug()
        logLevels = ['error', 'warning']

        if debug:
            logLevels.append('info')
            logLevels.append('success')

        logger.clear()
        logger.addTransport(XPlaneLogger.ConsoleTransport(), logLevels)

    def assertMatricesEqual(self,mA,mB,tolerance=FLOAT_TOLERANCE):
        for row_a,row_b in zip(mA,mB):
            self.assertFloatVectorsEqual(row_a, row_b, tolerance)

    # Utility method to check if objects are contained in file
    def assertObjectsInXPlaneFile(self, xplaneFile, objectNames):
        for name in objectNames:
            # TODO:  Remove/change
            self.assertIsNotNone(xplaneFile.objects[name])
            self.assertTrue(isinstance(xplaneFile.objects[name],xplane_primitive.XPlanePrimitive))
            self.assertEquals(xplaneFile.objects[name].blenderObject, bpy.data.objects[name])

    def assertXPlaneBoneTreeEqual(self, file_root_bone:xplane_bone.XPlaneBone, fixture_root_bone:xplane_bone.XPlaneBone)->None:
        """
        Recurses down two XPlaneBone trees, and compares each XPlaneBone's
        - xplaneObject
        - blenderObject
        - blenderBone

        self.xplaneFile and self.parent are not compared
        """
        assert file_root_bone
        assert fixture_root_bone

        def recursively_check(file_bone: xplane_bone.XPlaneBone,
                              fixture_bone: xplane_bone.XPlaneBone)->None:
            file_bone_name = getattr(file_bone.xplaneObject, 'name', 'None')
            fixture_bone_name = getattr(fixture_bone.xplaneObject, 'name', 'None')
            self.assertEqual(
                bool(file_bone.xplaneObject),
                bool(fixture_bone.xplaneObject),
                msg=f"File Bone '{file_bone.getName(ignore_indent_level=True)}'"\
                    f" and Fixture Bone '{file_bone.getName(ignore_indent_level=True)}'"\
                    f" don't have the same xplaneObject: ({file_bone_name, fixture_bone_name}),"
            )
            self.assertEqual(file_bone.blenderObject,
                             fixture_bone.blenderObject)
            self.assertEqual(file_bone.blenderBone,
                             fixture_bone.blenderBone)
            self.assertEqual(len(file_bone.children), len(fixture_bone.children))
            for child_file_bone, child_fixture_bone in zip(file_bone.children, fixture_bone.children):
                recursively_check(child_file_bone, child_fixture_bone)
        recursively_check(file_root_bone, fixture_root_bone)

    def assertFloatsEqual(self, a:float, b:float, tolerance:float = FLOAT_TOLERANCE):
        """
        Tests if floats are equal, with a default tollerance. The difference between this and assertAlmostEqual
        is that we use abs instead of round, then compare
        """
        if abs(a - b) < tolerance:
            return True
        else:
            raise AssertionError(f"{a} != {b}, within a tolerance of {tolerance}")

    def assertFloatVectorsEqual(self, a:int, b:int, tolerance:float = FLOAT_TOLERANCE):
        self.assertEquals(len(a), len(b))
        for a_comp, b_comp in zip(a, b):
            self.assertFloatsEqual(a_comp, b_comp, tolerance)

    def parseFileToLines(self, data:str)->List[Union[float,str]]:
        '''
        Turns a string of \n seperated lines into a List[Union[float,str]]
        without comments or 0 length strings. All numeric parts are converted
        '''
        lines = [] # type: List[Union[float,str]]
        def tryToFloat(part:str)->Union[float, str]:
            try:
                return float(part)
            except (TypeError, ValueError):
                return part

        for line in filter(lambda l: len(l) > 0 and l[0] != '#', data.split('\n')):
            if '#' in line:
                line = line[0:line.index('#')]
            line = line.strip()
            if line:
                lines.append(tuple(map(tryToFloat, line.split())))

        return lines

    def assertFilesEqual(self,
                         a: str,
                         b: str,
                         filterCallback:Optional[FilterLinesCallback] = None,
                         floatTolerance:float = FLOAT_TOLERANCE):
        '''
        a and b should be the contents of files a and b as returned
        from open(file).read()
        '''
        def isnumber(d):
            return isinstance(d, (float, int))

        linesA = self.parseFileToLines(a)
        linesB = self.parseFileToLines(b)

        # if a filter function is provided, additionally filter lines with it
        if filterCallback:
            linesA = list(filter(filterCallback, linesA))
            linesB = list(filter(filterCallback, linesB))

        # ensure same number of lines
        try:
            self.assertEquals(len(linesA), len(linesB))
        except AssertionError as e:
            only_in_a = (set(linesA) - set(linesB))
            only_in_b = (set(linesB) - set(linesA))
            diff = ">" + "\n>".join(
                        " ".join(map(str,l))
                        for l in (only_in_a if len(only_in_a) > len(only_in_b) else only_in_b))
            diff += "\n\n>" + "\n>".join(
                        " ".join(map(str,l))
                        for l in (only_in_a if len(only_in_a) < len(only_in_b) else only_in_b))

            raise AssertionError(
                f"Length of filtered parsed lines unequal: "
                f"{e.args[0]}\n{diff}\n"
            ) from None

        for lineIndex, (lineA, lineB) in enumerate(zip(linesA, linesB)):
            try:
                #print(f"lineA:{lineA}, lineB:{lineB}")
                self.assertEquals(len(lineA), len(lineB))
            except AssertionError as e:
                raise AssertionError(
                        f"Number of line components unequal: {e.args[0]}\n"
                        f"{lineIndex}> {lineA} ({len(lineA)})"
                        f"{lineIndex}> {lineB} ({len(lineB)})"
                    ) from None


            for linePos in range(0, len(lineA)):
                segmentA = lineA[linePos]
                segmentB = lineB[linePos]

                # assure same values (floats must be compared with tolerance)
                if isnumber(segmentA) and isnumber(segmentB):
                    #TODO: This is too simple! This will make call abs on the <value> AND <angle> in ANIM_rotate_key
                    # which are not semantically the same!
                    # Also not covered are PHI, PSI, and THETA!
                    segmentA = abs(segmentA) if "rotate" in lineA[0] or "manip_keyframe" in lineA[0] else segmentA
                    segmentB = abs(segmentB) if "rotate" in lineB[0] or "manip_keyframe" in lineB[0] else segmentB
                    try:
                        self.assertFloatsEqual(segmentA, segmentB, floatTolerance)
                    except AssertionError as e:
                        def make_context(source, segment)->str:
                            current_line = f"{lineIndex}> {' '.join(map(str, source[lineIndex]))}"
                            # Makes something like "?     ^~~~"
                            question_line = (
                                "?"
                                 + "^".rjust(len(" ".join(map(str,lineA[:linePos]))) + 4, " ")
                                 + "~"*(len(str(segment))-1)
                            )

                            return "\n".join((
                                    f"{lineIndex - 1}: {' '.join(map(str, source[lineIndex-1]))}" if lineIndex > 0 else "",
                                    current_line,
                                    question_line,
                                    f"{lineIndex + 1}: {' '.join(map(str, source[lineIndex+1]))}" if lineIndex < len(source) else "",
                                    ))

                        context_lineA = make_context(linesA, segmentA)
                        context_lineB = make_context(linesB, segmentB)

                        raise AssertionError(e.args[0] + "\n" + "\n\n".join((context_lineA, context_lineB))) from None
                else:
                    self.assertEquals(segmentA, segmentB)

    def assertFileOutputEqualsFixture(
            self,
            fileOutput:str,
            fixturePath:str,
            filterCallback:Optional[FilterLinesCallback] = None,
            floatTolerance:float = FLOAT_TOLERANCE) -> None:
        """
        Compares the output of XPlaneFile.write (a \n separated str) to a fixture on disk.

        A filterCallback ensures only matching lines are compared.
        Highly recommended, with as simple a function as possible to prevent fixture fragility.
        """
        with open(fixturePath, "r") as fixtureFile:
            fixtureOutput = fixtureFile.read()

        return self.assertFilesEqual(fileOutput, fixtureOutput, filterCallback, floatTolerance)

    def assertFileTmpEqualsFixture(
            self,
            tmpPath:str,
            fixturePath:str,
            filterCallback: Optional[FilterLinesCallback] = None,
            floatTolerance: float = FLOAT_TOLERANCE):
        tmpFile = open(tmpPath, 'r')
        tmpOutput = tmpFile.read()
        tmpFile.close()

        return self.assertFileOutputEqualsFixture(tmpOutput, fixturePath, filterCallback, floatTolerance)

    def assertLoggerErrors(self, expected_logger_errors:int)->None:
        """
        Asserts the logger has some number of errors, then clears the logger
        of all messages
        """
        try:
            found_errors = len(logger.findErrors())
            self.assertEqual(found_errors, expected_logger_errors)
        except AssertionError as e:
            raise AssertionError(f"Expected {expected_logger_errors} logger errors, got {found_errors}") from None
        else:
            logger.clearMessages()

    #TODO: Must filter warnings to have this be useful
    # Method: assertLoggerWarnings
    #
    # expected_logger_warnings - The number of warnings you expected to have happen
    # asserts the number of warnings and clears the logger of all messages
    #def assertLoggerWarnings(self, expected_logger_warnings):
    #    self.assertEqual(len(logger.findWarnings()), expected_logger_warnings)
    #    logger.clearMessages()

    def assertLayerExportEqualsFixture(self,
            layer_number:int,
            fixturePath:str,
            tmpFilename:Optional[str] = None,
            filterCallback:Optional[FilterLinesCallback] = None,
            floatTolerance:float = FLOAT_TOLERANCE)->None:
        """
        DEPRECATED: New unit tests should not use this!

        - layer_number starts at 0, as it used to access the scene.layers collection
        """
        #if not ('-q' in sys.argv or '--quiet' in sys.argv):
            #print("Comparing: '%s', '%s'" % (tmpFilename, fixturePath))

        out = self.exportRootObject(bpy.data.collections[f"Layer {layer_number + 1}"], tmpFilename)
        self.assertFileOutputEqualsFixture(out, fixturePath, filterCallback, floatTolerance)

    #TODO: Rename assertExportableRootExportEqualsFixture
    def assertRootObjectExportEqualsFixture(self,
            root_object:Union[bpy.types.Collection, bpy.types.Object, str],
            fixturePath: str = None,
            tmpFilename: Optional[str] = None,
            filterCallback:Optional[FilterLinesCallback] = None,
            floatTolerance: float = FLOAT_TOLERANCE):
        """
        Exports only a specific exportable root and compares the output
        to a fixutre.

        If filterCallback is None, no filter (besides stripping comments)
        will be used.
        """
        out = self.exportRootObject(root_object, tmpFilename)
        self.assertFileOutputEqualsFixture(out, fixturePath, filterCallback, floatTolerance)

    # asserts that an attributes object equals a dict
    def assertAttributesEqualDict(self,
                                  attrs:List[str],
                                  d:Dict[str, Any],
                                  floatTolerance:float = FLOAT_TOLERANCE):
        self.assertEquals(len(d), len(attrs), 'Attribute lists have different length')

        for name in attrs:
            attr = attrs[name]
            value = attr.getValue()
            expectedValue = d[name]

            if isinstance(expectedValue, list) or isinstance(expectedValue, tuple):
                self.assertTrue(isinstance(value, list) or isinstance(value, tuple), 'Attribute value for "%s" is no list or tuple but: %s' % (name, str(value)))
                self.assertEquals(len(expectedValue), len(value), 'Attribute values for "%s" have different length' % name)

                for i in range(0, len(expectedValue)):
                    v = value[i]
                    expectedV = expectedValue[i]

                    if isinstance(expectedV, float) or isinstance(expectedV, int):
                        self.assertFloatsEqual(expectedV, v, floatTolerance)
                    else:
                        self.assertEquals(expectedV, v, 'Attribute list value %d for "%s" is different' % (i, name))
            else:
                self.assertEquals(expectedValue, value, 'Attribute "%s" is not equal' % name)

    def exportLayer(self, layer_number:int, dest:str = None)->str:
        """
        DEPRECATED: New unit tests should not use this!

        - layer_number starts at 0, as it used to access the scene.layers collection
        - dest is a filepath without the file extension .obj, written to the TMP_DIR if not None
        """
        return self.exportRootObject(bpy.data.collections[f"Layer {layer_number + 1}"], dest)

    #TODO: Rename exportExportableRoot
    def exportRootObject(self, root_object:Union[bpy.types.Collection, bpy.types.Object, str], dest:str = None)->str:
        """
        Returns the result of calling xplaneFile.write(),
        where xplaneFile came from a root object (by name or Blender data).

        - dest is a filepath without the file extension .obj, written to the TMP_DIR if not None

        If root_object is an str, matching collections are looked up first.
        If you don't want an ambiguity of root objects, don't use the name twice
        """
        assert isinstance(root_object, (bpy.types.Collection, bpy.types.Object, str)), f"root_object type ({type(root_object)}) isn't allowed, must be Collection, Object, or str"
        if isinstance(root_object, str):
            try:
                root_object = bpy.data.collections[root_object]
            except KeyError:
                try:
                    root_object = bpy.data.objects[root_object]
                except KeyError:
                    assert False, f"{root_object} must be in bpy.data.collections|objects"

        xplaneFile = xplane_file.createFileFromBlenderRootObject(root_object)
        out = xplaneFile.write()

        if dest:
            with open(os.path.join(TMP_DIR, dest + '.obj'), 'w') as tmp_file:
                tmp_file.write(out)

        return out


class XPlaneAnimationTestCase(XPlaneTestCase):
    def setUp(self):
        super(XPlaneAnimationTestCase, self).setUp()

    def exportAnimationTestCase(self, name, dest):
        self.assertTrue(mappings[name])

        for layer in mappings[name]:
            outFile = os.path.join(dest, os.path.basename(mappings[name][layer]))
            print('Exporting to "%s"' % outFile)

            xplaneFile = xplane_file.createFileFromBlenderRootObject(bpy.data.collections[f"Layer {layer + 1}"])

            self.assertIsNotNone(xplaneFile, f"Unable to create XPlaneFile for {name} from Layer {layer + 1}")

            out = xplaneFile.write()

            outFile = open(outFile, 'w')
            outFile.write(out)
            outFile.close()

    def runAnimationTestCase(self, name, __dirname__):
        self.assertTrue(mappings[name])

        def filterLine(line):
            # only keep ANIM_ lines
            return isinstance(line[0], str) and ("ANIM" in line[0] or "TRIS" in line[0])

        for layer in mappings[name]:
            print('Testing animations against fixture "%s"' % mappings[name][layer])
            bpy.data.collections[f"Layer {layer + 1}"].hide_viewport = False
            xplaneFile = xplane_file.createFileFromBlenderRootObject(bpy.data.collections[f"Layer {layer + 1}"])

            self.assertIsNotNone(xplaneFile, 'Unable to create XPlaneFile for %s layer %d' % (name, layer))

            out = xplaneFile.write()
            fixtureFile = os.path.join(__dirname__, mappings[name][layer])

            self.assertTrue(os.path.exists(fixtureFile), 'File "%s" does not exist' % fixtureFile)
            self.assertFileOutputEqualsFixture(out, fixtureFile, filterLine)

def make_fixture_path(dirname,filename,sub_dir=""):
    return os.path.join(dirname, 'fixtures', sub_dir, filename + '.obj')

def runTestCases(testCases):
    #Until a better solution for knowing if the logger's error count should be used to quit the testing,
    #we are currently saying only 1 is allow per suite at a time (which is likely how it should be anyways)
    assert len(testCases) == 1, "Currently, only one test case per suite is supported at a time"
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(testCases[0])
    test_result = unittest.TextTestRunner().run(suite)

    # See XPlane2Blender/tests.py for documentation. The strings must be kept in sync!
    # This is not an optional debug print statement! The test runner needs this print statement to function
    print(f"RESULT: After {(test_result.testsRun)} tests got {len(test_result.errors)} errors, {len(test_result.failures)} failures, and {len(test_result.skipped)} skipped")
